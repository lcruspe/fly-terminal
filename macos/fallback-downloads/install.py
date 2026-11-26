from pathlib import Path
import shutil
root = Path("/opt/fly-terminal-downloads")
web = Path("/usr/share/selkies/web")
shutil.copyfile(root / "client.js", web / "fly-downloads.js")
index = web / "index.html"
html = index.read_text()
marker = '<script defer src="./fly-downloads.js"></script>'
if marker not in html:
    index.write_text(html.replace("</head>", marker + "</head>", 1))
nginx = Path("/etc/nginx/sites-available/default")
text = nginx.read_text()
if "location /fly-downloads/" not in text:
    text = text.replace("  location / {", """  location /fly-downloads/ {
    proxy_pass http://127.0.0.1:8789;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 3600s;
  }
  location / {""")
    nginx.write_text(text)
