"""Open AstroQuery in the same native WebView2 used by the desktop application.

The running local frontend/backend are reused; no external browser is launched.
Temporary automation flags and the demonstration profile belong to this process only.
"""
import argparse
import os
from pathlib import Path
from astroquery_ai.api.desktop import desktop_geometry,require_webview2
from astroquery_ai.runtime.paths import resource_root

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:5173')
    parser.add_argument('--debug-port',type=int,required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--title',default='AstroQuery AI')
    args=parser.parse_args()
    from urllib.parse import urlsplit
    if urlsplit(args.url).hostname not in {'127.0.0.1','localhost'}:raise ValueError('Native recording uses the local application only')
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']=(f'--remote-debugging-port={args.debug_port} --remote-debugging-address=127.0.0.1 '
        '--disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows')
    import webview
    require_webview2()
    window=webview.create_window(args.title,args.url,on_top=True,focus=True,**desktop_geometry())
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.start(gui='edgechromium',private_mode=False,storage_path=str(args.profile.resolve()),icon=str(resource_root()/'desktop/icon.ico'))

if __name__=='__main__':main()
