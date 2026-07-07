#!/usr/bin/env python3
"""
Fetch model files + description from printables.com without needing an account.
Uses printables.com's own GraphQL API (unauthenticated, same calls the site itself makes)
and falls back to scraping the "Details" tab HTML for print instructions.

No third-party deps: shells out to curl (present on macOS) and uses stdlib json/html.parser.

Usage:
  printables_fetch.py info <printables_url>            # list files + description as JSON
  printables_fetch.py download <printables_url> <dest_dir> [--file-id ID]  # download STL(s)
"""
import argparse
import html.parser
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

API_URL = "https://api.printables.com/graphql/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MODEL_FILES_QUERY = """
query ModelFiles($id: ID!) {
  model: print(id: $id) {
    id
    name
    filesType
    gcodes { ...GcodeDetail __typename }
    stls { ...StlDetail __typename }
    slas { ...SlaDetail __typename }
    otherFiles { ...OtherFileDetail __typename }
    __typename
  }
}
fragment GcodeDetail on GCodeType { id created name folder note printer { id name __typename } excludeFromTotalSum printDuration layerHeight nozzleDiameter material { id name __typename } weight fileSize filePreviewPath rawDataPrinter order __typename }
fragment OtherFileDetail on OtherFileType { id created name folder note fileSize filePreviewPath order __typename }
fragment SlaDetail on SLAType { id created name folder note expTime firstExpTime printer { id name __typename } printDuration layerHeight usedMaterial fileSize filePreviewPath order __typename }
fragment StlDetail on STLType { id created name folder note fileSize filePreviewPath order __typename }
"""

DOWNLOAD_LINK_MUTATION = """
mutation GetDownloadLink($id: ID!, $modelId: ID!, $fileType: DownloadFileTypeEnum!, $source: DownloadSourceEnum!) {
  getDownloadLink(id: $id, printId: $modelId, fileType: $fileType, source: $source) {
    ok
    errors { field messages __typename }
    output { link count ttl __typename }
    __typename
  }
}
"""


def extract_model_id(url: str) -> str:
    m = re.search(r"/model/(\d+)-", url)
    if not m:
        raise ValueError(f"Could not find a numeric model id in URL: {url}")
    return m.group(1)


def graphql(operation_name: str, query: str, variables: dict) -> dict:
    payload = json.dumps({"operationName": operation_name, "query": query, "variables": variables})
    result = subprocess.run(
        ["curl", "-sS", "-m", "20", "-X", "POST", API_URL,
         "-H", "Content-Type: application/json",
         "-H", f"User-Agent: {UA}",
         "-d", payload],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    if "errors" in data and not data.get("data"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


class _DescriptionExtractor(html.parser.HTMLParser):
    """Pulls text out of the <div class="user-inserted">...</div> details block."""

    SKIP_TAGS = {"script", "style", "noscript", "iframe"}

    def __init__(self):
        super().__init__()
        self.depth = None
        self.skip_depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if self.depth is not None:
            if tag in self.SKIP_TAGS:
                self.skip_depth += 1
            elif tag == "div":
                self.depth += 1
            elif tag in ("p", "li", "h1", "h2", "h3", "h4", "br"):
                self.chunks.append("\n")
        elif tag == "div" and "user-inserted" in (attrs_d.get("class") or ""):
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth is not None:
            if tag in self.SKIP_TAGS and self.skip_depth > 0:
                self.skip_depth -= 1
            elif tag == "div":
                self.depth -= 1
                if self.depth == 0:
                    self.depth = None

    def handle_data(self, data):
        if self.depth is not None and self.skip_depth == 0:
            self.chunks.append(data)

    def text(self) -> str:
        raw = "".join(self.chunks)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def fetch_description(model_url: str) -> str:
    result = subprocess.run(
        ["curl", "-sSL", "-m", "20", model_url, "-H", f"User-Agent: {UA}"],
        capture_output=True, text=True, check=True,
    )
    parser = _DescriptionExtractor()
    parser.feed(result.stdout)
    return parser.text()


def list_files(model_id: str) -> dict:
    data = graphql("ModelFiles", MODEL_FILES_QUERY, {"id": model_id})
    model = data["model"]
    if model is None:
        raise RuntimeError(f"Model {model_id} not found or not public")
    return model


def get_download_link(file_id: str, model_id: str, file_type: str) -> str:
    data = graphql("GetDownloadLink", DOWNLOAD_LINK_MUTATION, {
        "id": file_id, "modelId": model_id, "fileType": file_type, "source": "model_detail",
    })
    out = data["getDownloadLink"]
    if not out["ok"] or not out.get("output", {}).get("link"):
        raise RuntimeError(f"Could not get download link: {out.get('errors')}")
    return out["output"]["link"]


def download(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sSL", "-m", "60", url, "-o", str(dest)], check=True)


def cmd_info(args):
    model_id = extract_model_id(args.url)
    model = list_files(model_id)
    description = fetch_description(args.url)
    out = {
        "model_id": model_id,
        "name": model.get("name"),
        "description": description,
        "files": {
            "stls": [{"id": f["id"], "name": f["name"], "size": f["fileSize"]} for f in model.get("stls") or []],
            "gcodes": [{"id": f["id"], "name": f["name"], "size": f["fileSize"]} for f in model.get("gcodes") or []],
            "slas": [{"id": f["id"], "name": f["name"], "size": f["fileSize"]} for f in model.get("slas") or []],
            "other_files": [{"id": f["id"], "name": f["name"], "size": f["fileSize"]} for f in model.get("otherFiles") or []],
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_download(args):
    model_id = extract_model_id(args.url)
    model = list_files(model_id)
    dest_dir = Path(args.dest_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    candidates = list(model.get("stls") or []) + list(model.get("otherFiles") or [])
    if args.file_id:
        candidates = [f for f in candidates if str(f["id"]) == str(args.file_id)]
    if not candidates:
        print(json.dumps({"error": "No matching STL/file found for this model"}), file=sys.stderr)
        sys.exit(1)

    downloaded = []
    for f in candidates:
        link = get_download_link(f["id"], model_id, "stl")
        filename = f["name"] if f["name"].lower().endswith((".stl", ".3mf", ".step", ".stp")) else f["name"] + ".stl"
        dest = dest_dir / filename
        download(link, dest)
        downloaded.append(str(dest))
    print(json.dumps({"downloaded": downloaded}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="List files + description for a model URL")
    p_info.add_argument("url")
    p_info.set_defaults(func=cmd_info)

    p_dl = sub.add_parser("download", help="Download STL file(s) for a model URL")
    p_dl.add_argument("url")
    p_dl.add_argument("dest_dir")
    p_dl.add_argument("--file-id", help="Only download this specific file id (default: all STLs)")
    p_dl.set_defaults(func=cmd_download)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
