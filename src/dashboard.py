"""Create a self-contained HTML dashboard from solver result JSON files."""
import html
import json
from collections import Counter
from pathlib import Path


def load_results(log_dir="logs"):
    results = []
    for path in Path(log_dir).glob("result_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("date", path.stem.replace("result_", ""))
            results.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(results, key=lambda item: str(item.get("date", "")), reverse=True)


def build_dashboard(results):
    counts = Counter(item.get("status", "unknown") for item in results)
    total = len(results)
    successes = counts.get("accepted", 0) + counts.get("already_solved", 0)
    rate = round(successes * 100 / total) if total else 0
    rows = []
    for item in results:
        problem = item.get("problem") or {}
        title = html.escape(str(problem.get("title", "No problem metadata")))
        slug = problem.get("slug")
        if slug:
            safe_slug = html.escape(str(slug), quote=True)
            title = f'<a href="https://leetcode.com/problems/{safe_slug}/">{title}</a>'
        rows.append(
            "<tr><td>{}</td><td>#{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(item.get("date", "—"))[:19]),
                html.escape(str(problem.get("id", "—"))),
                title,
                html.escape(str(problem.get("difficulty", "—"))),
                html.escape(str(item.get("status", "unknown"))).replace("_", " "),
            )
        )
    if not rows:
        rows.append("<tr><td colspan='5'>No run history yet.</td></tr>")
    return """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LeetCode Auto-Solver Dashboard</title>
<style>
body{margin:0;padding:28px;background:#0b1020;color:#edf3ff;font:15px system-ui}
main{max-width:1000px;margin:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.card,section{background:#141c30;border:1px solid #26334d;border-radius:14px;padding:18px;margin:14px 0}
.label{color:#9aa8c2;font-size:12px;text-transform:uppercase}.value{font-size:32px;font-weight:700}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #26334d}
th{color:#9aa8c2;font-size:12px}a{color:#7dd3fc;text-decoration:none}
</style></head><body><main><p>DAILY AUTOMATION · LEETCODE</p><h1>Solver performance</h1>
<div class="cards"><div class="card"><div class="label">Total runs</div><div class="value">""" + str(total) + """</div></div>
<div class="card"><div class="label">Accepted / already solved</div><div class="value">""" + str(successes) + """</div></div>
<div class="card"><div class="label">Success rate</div><div class="value">""" + str(rate) + """%</div></div>
<div class="card"><div class="label">Needs attention</div><div class="value">""" + str(counts.get("failed", 0) + counts.get("validation_failed", 0) + counts.get("error", 0)) + """</div></div></div>
<section><h2>Recent activity</h2><table><thead><tr><th>Date</th><th>ID</th><th>Problem</th><th>Difficulty</th><th>Status</th></tr></thead>
<tbody>""" + "".join(rows) + """</tbody></table></section></main></body></html>"""


def main():
    output = Path("dashboard/index.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_dashboard(load_results()), encoding="utf-8")
    print(f"Dashboard generated: {output}")


if __name__ == "__main__":
    main()
