#!/usr/bin/env python3
"""
Download a fast monocular depth ONNX model into the repo's models/ directory.
Usage:
  python3 scripts/download_fast_depth.py --url <MODEL_URL>
Or set the FAST_DEPTH_URL environment variable.
If you already have a model, set FAST_DEPTH_ONNX_PATH or place the file at models/fast_depth.onnx.
"""

import os
import sys
import argparse
from pathlib import Path

try:
    from urllib.request import urlopen
    from urllib.error import URLError, HTTPError
except Exception:
    urlopen = None


def download(url: str, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {url} -> {out_path}")
    try:
        with urlopen(url) as r, open(out_path, 'wb') as f:
            chunk_size = 8192
            while True:
                chunk = r.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
    except HTTPError as e:
        print(f"HTTP error: {e.code} {e.reason}")
        return False
    except URLError as e:
        print(f"URL error: {e.reason}")
        return False
    except Exception as e:
        print(f"Download failed: {e}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='Download fast depth ONNX model')
    parser.add_argument('--url', '-u', help='Model URL (HTTP/HTTPS)', default=os.environ.get('FAST_DEPTH_URL'))
    parser.add_argument('--out', '-o', help='Output path (default: models/fast_depth.onnx)', default='models/fast_depth.onnx')
    args = parser.parse_args()

    if args.url is None:
        print('No URL provided. Set --url or FAST_DEPTH_URL environment variable to a direct ONNX file URL.')
        parser.print_help()
        sys.exit(2)

    if urlopen is None:
        print('urllib not available in this environment; cannot download.')
        sys.exit(1)

    out_path = Path(args.out)
    ok = download(args.url, out_path)
    if not ok:
        print('Failed to download the model.')
        sys.exit(1)
    print('Download complete.')
    print('Place the model at models/fast_depth.onnx or set FAST_DEPTH_ONNX_PATH to the file path.')


if __name__ == '__main__':
    main()
