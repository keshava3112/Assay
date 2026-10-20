"""Generate the demo web: two snapshots (August, October 2026) of fictional companies.

    python scripts/build_demo_corpus.py

All companies, people, investors and publishers are invented; every domain uses the
reserved .example TLD so nothing can be mistaken for a real site.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "assay" / "examples" / "demo"

NAV = '<nav><a href="/">Home</a> <a href="/about">About</a> <a href="/press">Press</a> <a href="/security">Security</a> <a href="/careers">Careers</a></nav>'
FOOT = "<footer>© 2026 · Privacy · Terms · Cookie settings · Contact sales</footer>"


def page(title: str, body: list[str], links: list[str] | None = None) -> str:
    ps = "\n".join(f"<p>{escape(p)}</p>" if not p.startswith("<") else p for p in body)
    extra = "".join(f'<li><a href="{escape(l)}">{escape(l)}</a></li>' for l in links or [])
    return (f"<!doctype html><html><head><title>{escape(title)}</title><style>body{{font-family:sans-serif}}</style>"
            f"<script>window.analytics=1</script></head><body>{NAV}<main><h1>{escape(title.split(' — ')[0])}</h1>"
            f"{ps}{'<ul>' + extra + '</ul>' if extra else ''}</main>{FOOT}</body></html>")


def company_pages(snapshot: str) -> dict[str, str]:
    oct_ = snapshot == "oct"
    p: dict[str, str] = {}

    # Kosha Credit: the clean match
    p["https://kosha.example"] = page("Kosha Credit — Working capital for India's small businesses", [
        "Kosha Credit offers working-capital loans and revolving credit lines to small manufacturers and distributors.",
        "Decisions in 48 hours, using GST and bank data rather than collateral.",
        "Kosha Credit is headquartered in Bengaluru and has disbursed over ₹900 crore since launch."])
    p["https://kosha.example/about"] = page("About — Kosha Credit", [
        "Kosha Credit was founded in 2021 by Meera Raghavan and Arjun Pillai.",
        "We are headquartered in Bengaluru, with teams in Mumbai and Delhi."])
    p["https://kosha.example/press"] = page("Press — Kosha Credit", [
        "March 12, 2026: Kosha Credit raises $18M Series A led by Northfield Ventures.",
        "Kosha Credit raised $18M in a Series A round in March 2026 to take its lending to 40 new cities."])
    p["https://kosha.example/security"] = page("Security — Kosha Credit", [
        "Kosha Credit is SOC 2 Type II certified and is audited every year by an independent firm."])

    # Paisaloom: Series A too long ago
    p["https://paisaloom.example"] = page("Paisaloom — Buy now, pay later for India", [
        "Paisaloom offers buy now, pay later credit at 4,000 partner stores.",
        "Paisaloom is headquartered in Mumbai."])
    p["https://paisaloom.example/press"] = page("Newsroom — Paisaloom", [
        "Paisaloom raised a $12M Series A in November 2024, led by Harbour Line Capital."])
    p["https://paisaloom.example/security"] = page("Trust — Paisaloom", ["Our platform is ISO 27001 certified."])

    # Udhaar Grid: bootstrapped in August, raises in October -> the monitor's new match
    p["https://udhaargrid.example"] = page("Udhaar Grid — Credit lines for kirana stores", [
        "Udhaar Grid gives neighbourhood kirana stores short-term credit lines to stock up before festivals.",
        "Udhaar Grid is headquartered in Pune."])
    p["https://udhaargrid.example/about"] = page("About — Udhaar Grid", [
        "Founded in 2022 by Kavya Deshmukh.",
        *(["Udhaar Grid now serves 18,000 stores across Maharashtra."] if oct_ else
          ["Udhaar Grid is bootstrapped and profitable, serving 11,000 stores across Maharashtra."])])
    if oct_:
        p["https://udhaargrid.example/press"] = page("Press — Udhaar Grid", [
            "October 6, 2026: Udhaar Grid raises a $9M Series A from Monsoon Capital to expand beyond Maharashtra.",
            "Udhaar Grid raised $9M in its Series A in October 2026."])

    # Ledgerline: lends, recent Series A, but headquartered abroad
    p["https://ledgerline.example"] = page("Ledgerline — Invoice financing for exporters", [
        "Ledgerline offers invoice financing to Indian exporters selling to the US and Europe.",
        "Ledgerline is headquartered in Singapore, with an engineering centre in Chennai."])
    p["https://ledgerline.example/press"] = page("Press — Ledgerline", [
        "Ledgerline raised a $15M Series A in January 2026."])

    # Tijori Pay: recent Series A, Indian, but explicitly does not lend
    p["https://tijoripay.example"] = page("Tijori Pay — Payments for D2C brands", [
        "Tijori Pay handles UPI, card and wallet payments for direct-to-consumer brands.",
        "Tijori Pay does not offer loans or credit; we focus on payments.",
        "Tijori Pay is headquartered in Hyderabad."])
    p["https://tijoripay.example/press"] = page("Press — Tijori Pay", [
        "April 2, 2026: Tijori Pay closes a $20M Series A."])

    # Saral Loans: match, ISO 27001
    p["https://saralloans.example"] = page("Saral Loans — Personal loans in minutes", [
        "Saral Loans offers personal loans to salaried professionals in tier-2 cities.",
        "Saral Loans is headquartered in Jaipur."])
    p["https://saralloans.example/about"] = page("About — Saral Loans", [
        "Saral Loans was founded in 2020.",
        "Saral Loans raised a ₹120 crore Series A in August 2025."])
    p["https://saralloans.example/security"] = page("Security — Saral Loans", [
        "Saral Loans is ISO 27001 certified."])

    # Anvil Finance: says it raised a Series A, but never says when
    p["https://anvilfinance.example"] = page("Anvil Finance — Equipment financing for clinics", [
        "Anvil Finance provides equipment financing to clinics and diagnostic labs.",
        "Anvil Finance is headquartered in New Delhi.",
        "Anvil Finance has raised its Series A and is hiring across India."])

    # Mitra Money: match; publishes SOC 2 in October
    p["https://mitramoney.example"] = page("Mitra Money — Small loans for gig workers", [
        "Mitra Money offers small loans to delivery partners and drivers, repaid from daily earnings.",
        "Mitra Money is headquartered in Kochi."])
    p["https://mitramoney.example/press"] = page("Press — Mitra Money", [
        "Mitra Money raised a $7M Series A in May 2026."])
    if oct_:
        p["https://mitramoney.example/security"] = page("Security — Mitra Money", [
            "Mitra Money completed its SOC 2 Type II audit in September 2026."])

    # Gullak: savings, not lending
    p["https://gullak.example"] = page("Gullak — Save a little, every day", [
        "Gullak helps families save with daily recurring deposits.",
        "Gullak does not offer loans.",
        "Gullak is headquartered in Ahmedabad."])

    # Noise: a personal blog that happens to talk about credit
    p["https://chaiandcode.example/credit-scoring-notes"] = page("Notes on a weekend credit-scoring project — Chai & Code", [
        "I spent a weekend in Bengaluru building a toy credit-scoring model for small loans.",
        "This is a personal blog; nothing here is a product."])

    # The publisher: a lead source whose outbound links reveal companies
    picks = ["https://kosha.example", "https://udhaargrid.example", "https://mitramoney.example",
             "https://anvilfinance.example", "https://saralloans.example"]
    p["https://fintechpulse.example/lending-startups-to-watch"] = page("India's lending startups to watch — FintechPulse", [
        "Our pick of Indian startups building loans and credit for the next billion borrowers.",
        "Kosha Credit, Udhaar Grid, Mitra Money, Anvil Finance and Saral Loans are on our list this year."], picks)
    if oct_:
        p["https://fintechpulse.example/udhaar-grid-series-a"] = page("Udhaar Grid raises $9M Series A — FintechPulse", [
            "Pune-based Udhaar Grid, which offers credit lines to kirana stores, has raised a $9M Series A."],
            ["https://udhaargrid.example"])
    return p


def write(snapshot: str, captured: str) -> None:
    out = ROOT / snapshot
    if out.exists():
        for f in out.rglob("*"):
            if f.is_file():
                f.unlink()
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"captured": captured, "pages": {}}
    for url, html in company_pages(snapshot).items():
        name = url.split("://")[1].replace("/", "__").replace(".", "_") + ".html"
        (out / name).write_text(html)
        manifest["pages"][url] = name
    (out / "corpus.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"{snapshot}: {len(manifest['pages'])} pages")


if __name__ == "__main__":
    write("aug", "2026-08-18T09:00:00")
    write("oct", "2026-10-19T09:00:00")
