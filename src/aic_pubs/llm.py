"""Second-pass review of rule-based leads with a free, locally run LLM.

Only leads (categories A-E, a few dozen a year) are reviewed, and the model
sees only the evidence sentences, so a 7-8B model on a free Colab T4 GPU
finishes a year in minutes. Verdicts are written to data/<year>/llm_review.json
and can be scored against data/<year>/reference_labels.csv with `evaluate`.
"""
import csv
import json
import re
from collections import Counter

from .config import load
from .screen import LEADS
from .sweep import DATA, load_screened

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
VERDICTS = ("yes", "likely", "no")

SYSTEM = """You audit scientific papers for a core microscopy facility: {facility}.
Decide whether the paper's imaging (or other work) was done using THIS facility.

Facility instruments: {instruments}.

Rules:
- "yes": the text acknowledges or credits the facility for imaging/microscopy, or says imaging was performed there.
- "likely": no explicit credit, but a facility instrument model is used and the authors are local.
- "no": the facility name appears only as an author affiliation; a vendor name is a reagent supplier; the imaging was done at another facility or institution; or a similar but different instrument.
{notes}
Answer with JSON only:
{{"used_facility": "yes|likely|no", "acknowledged": true|false, "cytometry_only": true|false, "instrument": "<instrument or null>", "confidence": <0-1>, "reason": "<one sentence>"}}"""


def _instrument_names(cfg):
    return ", ".join(i.id.removeprefix("scope-").removeprefix("retired-").replace("-", " ")
                     for i in cfg.instruments)


def build_messages(row, cfg):
    notes = "\n".join(f"- {n}" for n in cfg.raw.get("llm_prompt_notes") or [])
    system = SYSTEM.format(facility=cfg.raw["facility"]["name"], instruments=_instrument_names(cfg),
                           notes=notes)
    ev = "\n".join(f"- {s}" for s in row.get("evidence", [])) or "- (no evidence sentences)"
    user = (f"Title: {row.get('title') or '?'}\nJournal: {row.get('journal') or '?'}\n"
            f"Local (institution-affiliated) authors: {len(row.get('local_authors') or [])}\n"
            f"Corresponding e-mail at {'/'.join(cfg.email_domains)}: {row.get('local_email')}\n"
            f"Evidence sentences from the full text:\n{ev}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    verdict = str(v.get("used_facility", "")).lower().strip()
    v["used_facility"] = verdict if verdict in VERDICTS else "unparsed"
    v["raw"] = text[:500]
    return v


class LocalModel:
    """Hugging Face causal LM; 4-bit on a CUDA GPU, bfloat16 on CPU."""

    def __init__(self, model_id=DEFAULT_MODEL):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_id)
        kw = {}
        if torch.cuda.is_available():
            from transformers import BitsAndBytesConfig
            kw = {"device_map": "auto", "quantization_config": BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)}
        else:
            kw = {"torch_dtype": torch.bfloat16}
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **kw)
        self.model_id = model_id

    def __call__(self, messages, max_new_tokens=200):
        import torch
        kwargs = {"add_generation_prompt": True, "return_tensors": "pt", "return_dict": True}
        try:  # Qwen3-style models: disable "thinking" output
            inputs = self.tok.apply_chat_template(messages, enable_thinking=False, **kwargs)
        except TypeError:
            inputs = self.tok.apply_chat_template(messages, **kwargs)
        inputs = inputs.to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        return self.tok.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)


def review_year(year, model_id=DEFAULT_MODEL, limit=None, model=None):
    cfg = load()
    path = DATA / str(year) / "llm_review.json"
    done = json.loads(path.read_text()) if path.exists() else {}
    rows = [r for r in load_screened(year) if r["category"] in LEADS and r["doi"] not in done]
    rows = rows[:limit]
    model = model or LocalModel(model_id)
    for n, r in enumerate(rows, 1):
        v = parse(model(build_messages(r, cfg)))
        v["model"] = model.model_id
        done[r["doi"]] = v
        path.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"[{n}/{len(rows)}] {r['doi']}: {v['used_facility']}", flush=True)
    return path


def _score_lines(name, ref, pred):
    """ref/pred: {doi: 'yes'|'likely'|'no'}; yes+likely count as facility use."""
    pos = lambda v: v in ("yes", "likely")
    common = [d for d in ref if d in pred]
    c = Counter((pos(ref[d]), pos(pred[d])) for d in common)
    tp, fp, fn, tn = c[(True, True)], c[(False, True)], c[(True, False)], c[(False, False)]
    lines = [f"{name}: {len(common)} labelled leads",
             f"  TP {tp}  FP {fp}  FN {fn}  TN {tn}   precision {tp / max(tp + fp, 1):.2f}  "
             f"recall {tp / max(tp + fn, 1):.2f}  accuracy {(tp + tn) / max(len(common), 1):.2f}"]
    lines += [f"  disagrees: {d} label={ref[d]} predicted={pred[d]}"
              for d in common if pos(ref[d]) != pos(pred[d])]
    return lines


def _precision_lines(name, ref, flagged):
    """Precision among flagged papers, counting 'likely' as positive and as negative."""
    lab = [d for d in flagged if d in ref]
    strict = sum(ref[d] == "yes" for d in lab)
    loose = sum(ref[d] in ("yes", "likely") for d in lab)
    from .provenance import ci
    return [f"{name}: {len(flagged)} flagged (report/check), {len(lab)} labelled",
            f"  precision {ci(loose, len(lab))} counting 'likely' as use, "
            f"{ci(strict, len(lab))} counting only 'yes' (95% Wilson intervals)"]


def evaluate(year, review_path=None):
    """Honest evaluation of the rules against data/<year>/reference_labels.csv.

    Labels exist almost only for papers the rules flagged, so recall over the labels
    is not a recall estimate. What is reported instead:
      * precision among flagged papers (all flagged papers should be labelled),
        with and without 'likely' counted as use;
      * recall against the facility's own website list (an independent-ish sample of
        true AIC papers), overall, among screened papers and among papers with text;
      * how much of the year was never labelled.
    """
    with (DATA / str(year) / "reference_labels.csv").open(newline="", encoding="utf-8") as f:
        ref = {r["doi"]: r["used_facility"] for r in csv.DictReader(f)}
    rows = {r["doi"]: r for r in load_screened(year)}
    listed_path = DATA / str(year) / "facility_list.json"
    listed = set(json.loads(listed_path.read_text())) if listed_path.exists() else set()

    def block(name, prio):
        flagged = {d for d in rows if prio(d) in ("report", "check")}
        out = _precision_lines(name, ref, flagged)
        if listed:
            screened = listed & set(rows)
            with_text = {d for d in screened if rows[d].get("has_text")}
            hit = listed & flagged
            from .provenance import ci
            out.append(f"  recall vs website list: {len(hit)}/{len(listed)} = {ci(len(hit), len(listed))} "
                       f"(screened {len(hit)}/{len(screened)}, with text {len(hit & with_text)}/{len(with_text)})")
            missed = sorted(listed - flagged)
            out.append(f"  website-list papers not flagged: {', '.join(missed) or 'none'}")
        unlabelled = [d for d in rows if d not in ref]
        out.append(f"  labelled {len(ref)} of {len(rows)} papers; {len(unlabelled)} never labelled "
                   f"(recall outside the website list is unmeasured; label a random sample of 'low' papers)")
        missing = sorted(d for d in flagged if d not in ref)
        if missing:
            out.append(f"  WARNING {len(missing)} flagged papers have no label: {', '.join(missing[:8])}")
        return out

    lines = block("rules (public, no private inputs)", lambda d: rows[d].get("priority"))
    from .sweep import load_private
    private = load_private(year)
    if any(p.get("reasons") for p in private.values()):
        lines += [""] + block("rules + private inputs (bookings/staff)",
                              lambda d: private.get(d, {}).get("priority") or rows[d].get("priority"))
    path = review_path or DATA / str(year) / "llm_review.json"
    if path.exists():
        llm = {d: v["used_facility"] for d, v in json.loads(path.read_text()).items()}
        model = next(iter(json.loads(path.read_text()).values()), {}).get("model", "LLM")
        lines += [""] + _score_lines(model, ref, llm)
    return "\n".join(lines)
