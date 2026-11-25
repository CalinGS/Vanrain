"""Offline tests for the harness pieces that need no network and no model."""

from pathlib import Path

from harness import conditions, metrics, tasks
from harness.agents import DryRun, Limits, prompt
from harness.issue_seeds import extract, resolve_vanrain_seeds

TINY = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "tiny_repo"

ISSUE = """\
`checkout()` applies tax before the discount

Calling shop.checkout.checkout with a discount gives the wrong total.
I think with_tax is called on the wrong amount; see DiscountedOrder.

Traceback (most recent call last):
  File "shop/checkout.py", line 14, in checkout
  File "shop/pricing.py", line 13, in with_tax
ValueError: bad amount

See https://github.com/example/shop/issues/1 for details.
"""


def _task(iid: str, repo: str) -> tasks.Task:
    return tasks.Task(iid, repo, "abc", "issue", "", "")


# --- issue_seeds -------------------------------------------------------------


def test_extract_orders_traceback_first_then_code():
    m = extract(ISSUE)
    assert m.identifiers[:2] == ("with_tax", "checkout")  # innermost frame first
    assert "shop.checkout.checkout" in m.identifiers
    assert "DiscountedOrder" in m.identifiers
    assert "github.com" not in " ".join(m.identifiers)
    assert m.paths == ("shop/pricing.py", "shop/checkout.py")


def test_resolve_seeds_skips_vague_names_and_caps():
    from vanrain import api

    graph = api.open_repo(TINY, cache=False).graph
    seeds = resolve_vanrain_seeds(graph, extract(ISSUE), max_seeds=3)
    assert seeds[0] == "shop.pricing.with_tax"
    assert "shop.checkout.checkout" in seeds
    assert len(seeds) <= 3


# --- tasks -------------------------------------------------------------------


def test_select_pilot_is_deterministic_and_balanced():
    pool = [_task(f"{r.split('/')[1]}-{i}", r) for r in tasks.PILOT_REPOS for i in range(10)]
    pool.append(_task("django-1", "django/django"))
    a = tasks.select_pilot(pool, size=12, per_repo_cap=2)
    b = tasks.select_pilot(list(reversed(pool)), size=12, per_repo_cap=2)
    assert [t.instance_id for t in a] == [t.instance_id for t in b]
    assert len(a) == 12
    assert all(t.repo != "django/django" for t in a)
    per_repo = {r: sum(t.repo == r for t in a) for r in tasks.PILOT_REPOS}
    assert max(per_repo.values()) <= 2


def test_task_from_instance_parses_json_test_lists():
    t = tasks.Task.from_instance({
        "instance_id": "x-1", "repo": "o/x", "base_commit": "c",
        "problem_statement": "p", "FAIL_TO_PASS": '["t::a"]', "PASS_TO_PASS": "[]",
    })
    assert t.fail_to_pass == ("t::a",) and t.pass_to_pass == ()


# --- conditions --------------------------------------------------------------


def test_none_adds_nothing():
    out = conditions.build("none", TINY, ISSUE)
    assert out.text == "" and out.tokens == 0


def test_vanrain_conditions_respect_budget_and_share_framing():
    for name in ("vanrain_sig_first", "vanrain_sig_only", "vanrain_full_first"):
        out = conditions.build(name, TINY, ISSUE, budget=400)
        assert out.condition == name
        assert out.text.startswith(conditions.HEADING)
        assert "shop/checkout.py" in out.text
        # The budget covers symbols and their header lines, not the markdown
        # around them (title, file headings, fences), so the rendered block is
        # larger. The harness reports what the agent actually sees.
        assert out.tokens == metrics.count_tokens(out.text)
        assert 0 < out.tokens <= 400 * 1.5
        assert "shop.pricing.with_tax" in out.seeds


def test_sig_only_shows_no_bodies_beyond_seeds():
    full = conditions.build("vanrain_sig_first", TINY, ISSUE, budget=2000).text
    sig = conditions.build("vanrain_sig_only", TINY, ISSUE, budget=2000).text
    assert full != sig


def test_no_seed_gives_empty_context():
    out = conditions.build("vanrain_sig_first", TINY, "Something is slow, please help.")
    assert out.text == "" and out.notes == ["no seed resolved"]


# --- metrics -----------------------------------------------------------------


def test_classify_command():
    c = metrics.classify_command
    assert c("cat src/a.py") == ("read", ["src/a.py"])
    assert c("sed -n '10,40p' src/a.py") == ("read", ["src/a.py"])
    assert c("sed -i 's/a/b/' src/a.py")[0] == "edit"
    assert c("cat > src/a.py <<'EOF'")[0] == "edit"
    assert c("grep -rn with_tax . | head")[0] == "read"  # head shows content
    assert c("grep -rn with_tax .")[0] == "search"
    assert c("python -m pytest tests/test_a.py")[0] == "run"
    assert c("cd repo && ls")[0] == "search"


def test_classify_tool_and_tally():
    rec = metrics.RunRecord("x", "none", 0, "test", "m", 0)
    actions = [
        metrics.classify_tool("Read", {"file_path": "a.py"}),
        metrics.classify_tool("Grep", {"pattern": "x"}),
        metrics.classify_tool("Bash", {"command": "cat ./a.py"}),
        metrics.classify_tool("Edit", {"file_path": "a.py"}),
    ]
    metrics.tally(rec, actions)
    assert (rec.tool_calls, rec.file_reads, rec.searches, rec.edits) == (4, 2, 1, 1)
    assert rec.distinct_files_read == ["a.py"]


def test_record_totals_and_json(tmp_path):
    rec = metrics.RunRecord("x", "none", 0, "test", "m", 0)
    rec.calls = [metrics.CallUsage(100, 900, 0, 50, 1000, 50),
                 metrics.CallUsage(10, 1100, 0, 20, 1110, 20)]
    assert (rec.billed_input, rec.billed_output, rec.fixed_total) == (2110, 70, 2180)
    out = tmp_path / "runs.jsonl"
    metrics.append(rec, out)
    assert '"fixed_total": 2180' in out.read_text()


def test_gold_file_coverage():
    patch = "diff --git a/shop/pricing.py b/shop/pricing.py\n--- a\n+++ b\n" \
            "diff --git a/shop/util.py b/shop/util.py\n"
    assert metrics.patch_files(patch) == ["shop/pricing.py", "shop/util.py"]
    assert metrics.gold_file_coverage("## shop/pricing.py\n", patch) == 0.5
    assert metrics.gold_file_coverage("shop\\util.py:\n", patch) == 0.5
    assert metrics.gold_file_coverage("x", "") is None


# --- agents ------------------------------------------------------------------


def test_prompt_differs_only_by_context(tmp_path):
    t = tasks.Task("x-1", "o/x", "c", ISSUE, "", "")
    none = conditions.build("none", TINY, ISSUE)
    van = conditions.build("vanrain_sig_first", TINY, ISSUE)
    p0, p1 = prompt(t, none, Path("/repo")), prompt(t, van, Path("/repo"))
    assert p1.startswith(p0.rstrip("\n"))
    res = DryRun(tmp_path).run(t, Path("/repo"), p1, Limits())
    assert res.transcript_path.read_text(encoding="utf-8") == p1
