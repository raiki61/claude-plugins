# Fido.ps1 (pbatard/Fido) の手順を写したもの: ARM64 の Windows 11 ISO のダウンロードの口の URL を得る
import json, re, sys, time, uuid, urllib.request
EDITION = sys.argv[1] if len(sys.argv) > 1 else "3816"   # 3816 = Windows 11 Home/Pro/Edu ARM64 (Fido の表)
ORG, PROFILE, INST = "y6jn8c31", "606624d44113", "560dc9f3-1aa5-4a2f-b63c-9e18f8d0e175"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
sid = str(uuid.uuid4())
def get(url, ref=None):
    h = {"User-Agent": UA}
    if ref: h["Referer"] = ref
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return r.read().decode("utf-8", "replace")
get(f"https://vlscppe.microsoft.com/tags?org_id={ORG}&session_id={sid}")
js = get(f"https://ov-df.microsoft.com/mdt.js?instanceId={INST}&PageId=si&session_id={sid}")
w = re.search(r"[?&]w=([A-F0-9]+)", js).group(1); rt = re.search(r'rticks="\+?(\d+)', js).group(1)
get(f"https://ov-df.microsoft.com/?session_id={sid}&CustomerId={INST}&PageId=si&w={w}&mdt={int(time.time()*1000)}&rticks={rt}")
base = "https://www.microsoft.com/software-download-connector/api"
for _ in range(3):
    skus = json.loads(get(f"{base}/getskuinformationbyproductedition?profile={PROFILE}&productEditionId={EDITION}&SKU=undefined&friendlyFileName=undefined&Locale=en-US&sessionID={sid}"))
    if skus.get("Skus"): break
    time.sleep(2)
sku = next(s for s in skus["Skus"] if s["Language"] == "English")
links = json.loads(get(f"{base}/GetProductDownloadLinksBySku?profile={PROFILE}&productEditionId=undefined&SKU={sku['Id']}&friendlyFileName=undefined&Locale=en-US&sessionID={sid}", ref="https://www.microsoft.com/software-download/windows11"))
if links.get("Errors"): sys.exit(json.dumps(links["Errors"]))
for o in links["ProductDownloadOptions"]:
    print(o["DownloadType"], o["Uri"])
