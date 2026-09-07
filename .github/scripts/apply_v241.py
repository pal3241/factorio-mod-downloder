from pathlib import Path

root = Path(__file__).resolve().parents[2]
flet_path = root / "flet_app.py"
text = flet_path.read_text(encoding="utf-8")
old = '''                control = ft.TextField(\n                    label=label,\n                    value=value_text(current),\n                    helper_text=" · ".join(helper),\n                    disabled=disabled,\n                    dense=True,\n                )\n'''
new = '''                helper_line = " · ".join(helper)\n                control = ft.TextField(\n                    label=label,\n                    value=value_text(current),\n                    disabled=disabled,\n                    dense=True,\n                )\n'''
if old not in text:
    raise SystemExit("target TextField block not found")
text = text.replace(old, new, 1)
old2 = '''                content=ft.Column(spacing=5, controls=[\n                    control,\n                    ft.Text(details, size=9, color="#77716b"),\n                ]),\n'''
new2 = '''                content=ft.Column(spacing=5, controls=[\n                    control,\n                    *([ft.Text(helper_line, size=9, color="#77716b")] if setting.get("type") != "bool-setting" else []),\n                    ft.Text(details, size=9, color="#77716b"),\n                ]),\n'''
if old2 not in text:
    raise SystemExit("target settings control content block not found")
text = text.replace(old2, new2, 1)
flet_path.write_text(text, encoding="utf-8")

pyproject = root / "pyproject.toml"
p = pyproject.read_text(encoding="utf-8")
p = p.replace('version = "2.4.0"', 'version = "2.4.1"', 1)
pyproject.write_text(p, encoding="utf-8")

print("Applied v2.4.1 Flet TextField compatibility hotfix")
