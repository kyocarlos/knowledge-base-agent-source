FROM km-chat-v2-secure:open-files-20261031-on-feed-c7869ce
COPY ctx/ /app/
COPY patch_register.py /tmp/patch_register.py
RUN python /tmp/patch_register.py /app/src/web_api/__init__.py \
 && python -m py_compile /app/src/web_api/__init__.py /app/src/web_api/rca_routes.py /app/src/report_numeric/compare.py /app/src/report_numeric/rca.py \
 && python -c "import ast,sys; [ast.parse(open(f,encoding='utf-8').read()) for f in sys.argv[1:]]" /app/src/web_api/rca_routes.py \
 && rm /tmp/patch_register.py
