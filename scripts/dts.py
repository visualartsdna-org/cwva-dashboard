"""DTS, driven from the command line — an operator entry point.

    python scripts/dts.py create --doc 'ChatGPT-….md' --label '…' --definition-from-doc
    python scripts/dts.py status

**It builds the real app**, rather than assembling a registry of its own.
`create_app` resolves the active layout, warms the SHACL shapes before the
worker forks, loads the ontology and the artist profiles, and opens the drop
folder from config — five things a script that re-derived them would
eventually get subtly wrong, pointing at a different tree than the dashboard
it is meant to be driving. Nothing is served; only the machinery is used.

Everything it writes is left UNCOMMITTED in the QA tree, like every other
writer: review it at Preview Staged and distribute it through the ordinary
gated exit.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cwva_dashboard.dts.documents import first_prompt
from cwva_dashboard.config import load_config as cfgmod_load
from cwva_dashboard.dts.pipeline import DTS, create_entity
from cwva_dashboard.dts.state import queue_of


#: The config this invocation selected, for the commands that read the `dts`
#: section. A module global because every command needs it and none of them
#: takes it: threading it through nine signatures to reach two `load_config`
#: calls would be the kind of change nobody makes, which is how the bare calls
#: survived.
_SELECTED_CONFIG: str = ""


def _cfg() -> dict:
    return (cfgmod_load(_SELECTED_CONFIG) if _SELECTED_CONFIG
            else cfgmod_load())


def _build(config_path: str = "") -> tuple[DTS, object]:
    from cwva_dashboard.ai_service import AIService
    from cwva_dashboard.main import _trusted_fileops, create_app

    # `create_app` already resolves CWVA_DASHBOARD_CONFIG; a `--config` on the
    # command line overrides it, so the two selectors agree with every other
    # operator script here.
    app = create_app(config_path=config_path) if config_path else create_app()
    st = app.state
    dts = DTS(
        dispatch=st.dash.dispatch,
        layout=st.layout,
        domain=st.domain,
        inbox=st.inbox,
        trusted_ops=_trusted_fileops(st.dash.sandbox_root, st.config),
        root=st.dash.sandbox_root,
        ai=AIService(),
    )
    return dts, app


def _store(dts) -> "Graph":
    """The whole QA store as one graph — the thesaurus DTS reads, plus the
    records it needs to resolve. Read once per command."""
    from rdflib import Graph

    g = Graph()
    root = Path(dts.root)
    for sub in ("ttl",):
        for f in (root / sub).rglob("*.ttl"):
            try:
                g.parse(f, format="turtle")
            except Exception:
                continue
    return g


def _entity(g, guid: str):
    """An entity by guid, with the handful of facts the stages need."""
    from rdflib import URIRef
    from rdflib.namespace import RDFS

    from cwva_dashboard.dts.state import THE

    uri = URIRef(f"http://visualartsdna.org/work/{guid}")
    doc = g.value(uri, THE.mdDocument)
    return {
        "uri": str(uri),
        "guid": guid,
        "label": str(g.value(uri, RDFS.label) or ""),
        "document": str(doc).rsplit("/", 1)[-1] if doc else "",
        "topics": [str(t) for t in g.objects(uri, THE.topic)],
    }


def _cache_path(dts, guid: str, stage: str) -> str:
    """In-flight proposals live in `.qa/`, which is gitignored: they are not a
    record of anything until a curator has decided, and `evidence/` is for
    what was decided."""
    return f".qa/dts/{guid}/{stage}.json"


def _arg(argv, name, default=""):
    return argv[argv.index(name) + 1] if name in argv else default


def _entity_path(dts, guid: str) -> str:
    return f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl"


def _guard(dts, guid: str, uri: str, stage: str) -> int:
    """Refuse a proposing stage that is not next, BEFORE the model is called.

    `expect_stage` already guarded the WRITES, which made a mis-ordered stage
    all-or-nothing in the store. It did not guard the COST or the cache: a
    second `derive` on an already-derived entity paid for a second model call,
    overwrote the cached proposals the curator would see, and only then was
    refused — leaving the curation screen offering one set of concepts while
    the record's own evidence stated a different one (2026-10-01, caught by
    comparing the two files' mtimes).

    The recorder's check stays as the backstop. This one makes the refusal free.
    """
    from cwva_dashboard.dts.pipeline import StageError

    try:
        dts.expect_stage(_entity_path(dts, guid), uri, stage)
    except StageError as exc:
        print(f"error: {exc}")
        return 1
    return 0


def cmd_create(dts, argv) -> int:
    doc = _arg(argv, "--doc")
    if not doc:
        print("error: --doc <filename in the drop folder> is required")
        return 2
    label = _arg(argv, "--label")
    topic = [t for t in _arg(argv, "--topic").split(",") if t]
    note = _arg(argv, "--note")
    tags = [t for t in _arg(argv, "--tag").split(",") if t]
    definition = _arg(argv, "--definition")

    if not definition:
        # The first human turn in the document, which is what every criticism
        # record in the store carries as its `skos:definition`.
        source = dts.inbox.resolve(doc, "markdown")
        definition = first_prompt(Path(source).read_text(encoding="utf-8"))
        if not definition:
            print(f"error: no human turn found in {doc}; pass --definition")
            return 1

    out = create_entity(
        dts, label=label, topic=topic, definition=definition,
        md_document=doc, tags=tags,
        notes=[{"type": "note", "text": note}] if note else None,
    )
    print(json.dumps(out.__dict__, indent=2))
    print(f"\ndefinition: {definition}")
    return 0


def cmd_derive(dts, argv) -> int:
    """Stage 1: propose concepts. Writes NOTHING into the store."""
    import pickle

    from cwva_dashboard import config as cfgmod
    from cwva_dashboard.dts.derive import derive, record_derivation
    from cwva_dashboard.dts.thesaurus import (format_for_prompt, read_label_index,
                                              read_scoped, schemes_for)

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    g = _store(dts)
    ent = _entity(g, guid)
    if not ent["document"]:
        print(f"error: {guid} cites no markdown document")
        return 1

    if _guard(dts, guid, ent["uri"], "derived"):
        return 1

    prefixes = {"the": "http://visualartsdna.org/thesaurus/"}
    dts_cfg = (_cfg().get("dts") or {})
    chosen = schemes_for(ent["topics"], dts_cfg, prefixes=prefixes)
    scoped = read_scoped(g, chosen.get("context") or [], prefixes=prefixes)

    res = derive(
        dts, entity_uri=ent["uri"], document_name=ent["document"],
        document_text=dts.document_text(ent["document"]),
        existing_block=format_for_prompt(scoped), scheme=chosen,
        label_index=read_label_index(g), thesaurus=g,
        limit=int(dts_cfg.get("derive_limit") or 0),
    )
    if not res.ok:
        print(f"derivation failed: {res.error}")
        return 1

    # Cached so curation is a separate act and does not pay for the call again.
    dts.trusted_ops.write_text(
        _cache_path(dts, guid, "derive"),
        json.dumps({"entity": res.entity, "document": res.document,
                    "model": res.model, "scheme_topic": chosen.get("topic", ""),
                    # Carried so the evidence record can state what the run
                    # cost. Curation is a separate command reading this cache,
                    # and a cost of zero in the record reads as "free".
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "proposals": [p.__dict__ for p in res.proposals]},
                   indent=2, default=lambda o: o.__dict__),
        make_parents=True)

    print(f"{ent['label']} — {res.document}")
    print(f"model {res.model}, {res.input_tokens}+{res.output_tokens} tokens, "
          f"schemes for topic {chosen.get('topic') or '(default)'}")
    print(f"counts: {res.counts()}\n")
    for p in res.proposals:
        near = ", ".join(f"{n.label}={n.distance:.2f}" for n in p.near[:3])
        print(f"[{p.status:10}] {p.label}")
        print(f"     {p.definition[:110]}")
        print(f"     broader={p.broader_label or '-'} | ref={p.wikipedia_url or '-'}")
        print(f"     phrase={p.grounding_phrase!r} grounded={p.grounded}")
        if near:
            print(f"     near: {near}")
        if p.notes:
            print(f"     ! {'; '.join(p.notes)}")
    # The proposal record and the `derived` stamp: stage 1 is done and the
    # entity is in queue 2, waiting for a curator. No concepts reach the
    # vocabulary until one decides.
    stamped = record_derivation(
        dts, res,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl")
    print(f"\nstamped : {stamped['stage']} -> {stamped['stamps']}")
    print("No concepts written yet. Curate with:")
    print(f"  dts.py curate-derive --entity {guid} --exclude '<label>,<label>'")
    return 0


def cmd_curate_derive(dts, argv) -> int:
    """The curator's include/exclude, then the three writes and the stamp."""
    from cwva_dashboard import config as cfgmod
    from cwva_dashboard.dts.derive import DerivationResult, Proposal, commit_derivation
    from cwva_dashboard.dts.grounding import Neighbour
    from cwva_dashboard.dts.session import current as session_current
    from cwva_dashboard.dts.thesaurus import schemes_for

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    cached = json.loads(dts.read_text(_cache_path(dts, guid, "derive")))
    proposals = []
    for d in cached["proposals"]:
        near = [Neighbour(**n) for n in d.pop("near", [])]
        proposals.append(Proposal(**{**d, "near": near}))
    res = DerivationResult(entity=cached["entity"], document=cached["document"],
                           model=cached["model"], proposals=proposals,
                           input_tokens=int(cached.get("input_tokens") or 0),
                           output_tokens=int(cached.get("output_tokens") or 0))

    excluded = {x.strip() for x in _arg(argv, "--exclude").split(",") if x.strip()}
    unknown = excluded - {p.label for p in proposals}
    if unknown:
        print(f"error: nothing proposed by that name: {', '.join(sorted(unknown))}")
        return 1
    included = {p.label for p in proposals
                if p.label not in excluded and p.include_by_default}

    g = _store(dts)
    prefixes = {"the": "http://visualartsdna.org/thesaurus/"}
    dts_cfg = (_cfg().get("dts") or {})
    table = schemes_for(_entity(g, guid)["topics"], dts_cfg, prefixes=prefixes)
    # ONE vocabulary file per session, merged into. Started on demand: a run
    # that refused until you named it would be a step people forget.
    sess = session_current(dts)

    out = commit_derivation(
        dts, res, included=included,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl",
        vocab_dir=dts.layout.dir("vocab_ttl"), vocab_name=sess.vocab_name,
        thesaurus=g,
        scheme_table=table, prefixes=prefixes,
        namespace="http://visualartsdna.org/thesaurus",
    )
    print(f"kept    ({len(out['kept'])}): {', '.join(out['kept'])}")
    print(f"dropped ({len(out['dropped'])}): {', '.join(out['dropped']) or '-'}")
    for c in out["concepts"]:
        print(f"   {c['label']:32} -> {c['scheme'].rsplit('/', 1)[-1]:20} "
              f"({c['_scheme_rule']})")
    written = out["written"]
    print(f"\nsession : {sess.id}"
          + (f" ({sess.label})" if sess.label else ""))
    print(f"wrote   : {written.get('path', '-')}"
          + (f"  (merged: +{written.get('added_triples', 0)} triples)"
             if written.get("merged_into") else "  (new file)"))
    print(f"stamped : {out['stamped']['stage']} -> {out['stamped']['stamps']}")
    return 0


def cmd_tag(dts, argv) -> int:
    """Stage 2: which existing concepts does this criticism discuss?"""
    from cwva_dashboard import config as cfgmod
    from cwva_dashboard.dts.tag import record_tagging, tag
    from cwva_dashboard.dts.thesaurus import (format_for_prompt, read_scoped,
                                              schemes_for)

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    g = _store(dts)
    ent = _entity(g, guid)
    if _guard(dts, guid, ent["uri"], "tagged"):
        return 1
    prefixes = {"the": "http://visualartsdna.org/thesaurus/"}
    dts_cfg = (_cfg().get("dts") or {})
    chosen = schemes_for(ent["topics"], dts_cfg, prefixes=prefixes)
    # The concepts this stage may choose from INCLUDE the ones derivation just
    # wrote, because the thesaurus is read from the QA store rather than from a
    # downstream server (§9.1). That is the whole reason DTS can be done in one
    # sitting with nothing distributed in between.
    scoped = read_scoped(g, chosen.get("context") or [], prefixes=prefixes)
    res = tag(dts, entity_uri=ent["uri"], document_name=ent["document"],
              document_text=dts.document_text(ent["document"]),
              existing_block=format_for_prompt(scoped),
              known_uris={c.uri for c in scoped},
              limit=int(dts_cfg.get("tag_limit") or 0), thesaurus=g)
    if not res.ok:
        print(f"tagging failed: {res.error}")
        return 1
    dts.trusted_ops.write_text(
        _cache_path(dts, guid, "tag"),
        json.dumps({"entity": res.entity, "document": res.document,
                    "model": res.model, "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "tags": [t.__dict__ for t in res.tags]}, indent=2),
        make_parents=True)
    print(f"{ent['label']} — {res.document}")
    print(f"model {res.model}, {res.input_tokens}+{res.output_tokens} tokens, "
          f"{len(scoped)} concepts offered")
    print(f"counts: {res.counts()}\n")
    for t in res.tags:
        print(f"[{t.status:10}] {t.label or t.uri:38} conf={t.confidence or '-':6} "
              f"grounded={t.grounded}")
        print(f"     phrase={t.grounding_phrase!r}")
        if t.notes:
            print(f"     ! {'; '.join(t.notes)}")
    stamped = record_tagging(
        dts, res,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl")
    print(f"\nstamped : {stamped['stage']} -> {stamped['stamps']}")
    print("No tags placed yet. Curate with:")
    print(f"  dts.py curate-tag --entity {guid} --exclude '<label>,<label>'")
    return 0


def cmd_curate_tag(dts, argv) -> int:
    from cwva_dashboard.dts.tag import Tag, TaggingResult, commit_tagging

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    cached = json.loads(dts.read_text(_cache_path(dts, guid, "tag")))
    tags = [Tag(**d) for d in cached["tags"]]
    res = TaggingResult(entity=cached["entity"], document=cached["document"],
                        model=cached["model"], tags=tags,
                        input_tokens=int(cached.get("input_tokens") or 0),
                        output_tokens=int(cached.get("output_tokens") or 0))
    excluded = {x.strip() for x in _arg(argv, "--exclude").split(",") if x.strip()}
    by_label = {t.label: t.uri for t in tags}
    unknown = excluded - set(by_label)
    if unknown:
        print(f"error: nothing tagged by that name: {', '.join(sorted(unknown))}")
        return 1
    included = {t.uri for t in tags
                if t.label not in excluded and t.include_by_default}
    out = commit_tagging(
        dts, res, included=included,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl")
    print(f"kept    ({len(out['kept'])}): {', '.join(out['kept'])}")
    print(f"dropped ({len(out['dropped'])}): {', '.join(out['dropped']) or '-'}")
    placed = out["placed"]
    for row in placed.get("placed", []):
        print(f"   {str(row)[:130]}")
    if placed.get("tied"):
        print(f"   TIED (to the hygiene ledger): {placed['tied']}")
    if placed.get("unplaced"):
        print(f"   UNPLACED: {placed['unplaced']}")
    print(f"stamped : {out['stamped']['stage']} -> {out['stamped']['stamps']}")
    return 0


def cmd_summarize(dts, argv) -> int:
    """Stage 3: one paragraph a reader can decide from."""
    from cwva_dashboard.dts.summarize import record_summary, summarize

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    ent = _entity(_store(dts), guid)
    if _guard(dts, guid, ent["uri"], "summarized"):
        return 1
    res = summarize(dts, entity_uri=ent["uri"], document_name=ent["document"],
                    document_text=dts.document_text(ent["document"]))
    if not res.ok:
        print(f"summarization failed: {res.error}")
        return 1
    dts.trusted_ops.write_text(
        _cache_path(dts, guid, "summarize"),
        json.dumps({"entity": res.entity, "document": res.document,
                    "model": res.model, "summary": res.summary,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "notes": res.notes}, indent=2),
        make_parents=True)
    stamped = record_summary(
        dts, res,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl")
    print(f"{ent['label']} — {res.document}")
    print(f"model {res.model}, {res.input_tokens}+{res.output_tokens} tokens, "
          f"{res.words} words, {res.paragraphs} paragraph(s)")
    for note in res.notes:
        print(f"  ! {note}")
    print(f"\n{res.summary}\n")
    print(f"stamped : {stamped['stage']} -> {stamped['stamps']}")
    print("Not on the record yet. Accept with:")
    print(f"  dts.py curate-summary --entity {guid} --accept")
    return 0


def cmd_curate_summary(dts, argv) -> int:
    """Accept or send back. There is nothing to include or exclude in one
    paragraph, so this is the one stage whose curation is a verdict."""
    from cwva_dashboard.dts.summarize import SummaryResult, commit_summary

    guid = _arg(argv, "--entity")
    if not guid:
        print("error: --entity <guid> is required")
        return 2
    if "--accept" not in argv:
        print("Send-back is not built: with no re-runs, the only way back is "
              "`dts.py reset --entity <guid>`. Pass --accept to publish it.")
        return 2
    cached = json.loads(dts.read_text(_cache_path(dts, guid, "summarize")))
    res = SummaryResult(entity=cached["entity"], document=cached["document"],
                        model=cached["model"], summary=cached["summary"],
                        input_tokens=cached.get("input_tokens", 0),
                        output_tokens=cached.get("output_tokens", 0),
                        notes=cached.get("notes") or [])
    out = commit_summary(
        dts, res,
        entity_path=f"{dts.layout.dir('work_ttl').rstrip('/')}/{guid}.ttl")
    print(f"wrote   : {out['written']['words']} words onto {out['written']['path']}")
    print(f"stamped : {out['stamped']['stage']} -> {out['stamped']['stamps']}")
    return 0


def cmd_session(dts, argv) -> int:
    """Show the session in progress, or start a new one.

    A session is what a person means by "a run of DTS" — the documents they
    sat down to process — and it names the one vocabulary file they all write
    into.
    """
    from cwva_dashboard.dts.session import current as session_current
    from cwva_dashboard.dts.session import start as session_start

    if "--new" in argv:
        sess = session_start(dts, label=_arg(argv, "--label"))
        print(f"started {sess.id}" + (f" ({sess.label})" if sess.label else ""))
    else:
        sess = session_current(dts)
        print(f"current {sess.id}" + (f" ({sess.label})" if sess.label else ""))
    print(f"  started : {sess.started}")
    print(f"  vocab   : {dts.layout.dir('vocab_ttl').rstrip('/')}/{sess.vocab_name}")
    return 0


def cmd_status(dts, argv) -> int:
    """Every DTS entity and the queue it sits in."""
    from rdflib import Graph, URIRef
    from rdflib.namespace import RDFS

    from cwva_dashboard.dts.state import THE

    listed = dts.call("fs.list", {"path": dts.layout.dir("work_ttl")})
    rows = []
    for entry in listed.get("entries", []):
        name = entry["name"] if isinstance(entry, dict) else str(entry)
        if not name.endswith(".ttl"):
            continue
        rel = f"{dts.layout.dir('work_ttl').rstrip('/')}/{name}"
        g = Graph()
        try:
            g.parse(data=dts.read_text(rel), format="turtle")
        except Exception:
            continue
        for s in set(g.subjects(None, THE.AI)):
            rows.append((queue_of(g, s), str(g.value(s, RDFS.label) or s), str(s)))
    for queue, label, uri in sorted(rows):
        print(f"{queue:32} {label[:48]:50} {uri.rsplit('/', 1)[-1]}")
    print(f"\n{len(rows)} AI entities")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    global _SELECTED_CONFIG
    _SELECTED_CONFIG = (argv[argv.index("--config") + 1]
                        if "--config" in argv
                        else os.environ.get("CWVA_DASHBOARD_CONFIG", ""))
    dts, _app = _build(_SELECTED_CONFIG)
    # The command is the first NON-FLAG argument, so `--config X status` reads
    # the same as `status --config X`. Taking argv[1] made the first form
    # report "unknown command '--config'", which is a true statement about the
    # wrong thing.
    command = ""
    skip = False
    for arg in argv[1:]:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            skip = arg == "--config"
            continue
        command = arg
        break
    if command == "create":
        return cmd_create(dts, argv)
    if command == "status":
        return cmd_status(dts, argv)
    if command == "derive":
        return cmd_derive(dts, argv)
    if command == "curate-derive":
        return cmd_curate_derive(dts, argv)
    if command == "tag":
        return cmd_tag(dts, argv)
    if command == "curate-tag":
        return cmd_curate_tag(dts, argv)
    if command == "session":
        return cmd_session(dts, argv)
    if command == "summarize":
        return cmd_summarize(dts, argv)
    if command == "curate-summary":
        return cmd_curate_summary(dts, argv)
    print(f"unknown command {command!r}; try "
          "create, derive, curate-derive or status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
