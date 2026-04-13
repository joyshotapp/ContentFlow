import re
path = r'c:\Users\User\Desktop\ContentFlow\src\contentflow\admin\app.py'
with open(path, encoding='utf-8') as f:
    content = f.read()
pattern = r'templates[.]TemplateResponse[(]("[-_a-zA-Z]+[.]html")'
repl = r'templates.TemplateResponse(request, \1'
fixed = re.sub(pattern, repl, content)
count = content.count('templates.TemplateResponse(')
fixed_count = fixed.count('templates.TemplateResponse(request,')
print(f'Total: {count}, Fixed: {fixed_count}')
with open(path, 'w', encoding='utf-8') as f:
    f.write(fixed)
print('Done')
