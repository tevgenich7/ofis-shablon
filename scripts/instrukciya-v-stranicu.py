import html, re, sys
src = open('УСТАНОВКА.md', encoding='utf-8').read().split('\n')
out, i = [], 0
def inline(t):
    t = html.escape(t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    t = re.sub(r'(https?://[^\s,)]+)', r'<a href="\1">\1</a>', t)
    return t
buf_p, buf_li, buf_ol = [], [], []
def flush():
    global buf_p, buf_li, buf_ol
    if buf_p: out.append('<p>' + inline(' '.join(buf_p)) + '</p>'); buf_p = []
    if buf_li: out.append('<ul>' + ''.join('<li>%s</li>' % inline(x) for x in buf_li) + '</ul>'); buf_li = []
    if buf_ol: out.append('<ol>' + ''.join('<li>%s</li>' % inline(x) for x in buf_ol) + '</ol>'); buf_ol = []
while i < len(src):
    l = src[i]
    if l.strip().startswith('```'):
        flush(); i += 1; code = []
        while i < len(src) and not src[i].strip().startswith('```'):
            code.append(src[i]); i += 1
        out.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>'); i += 1; continue
    if l.startswith('# '): flush(); out.append('<h1>%s</h1>' % inline(l[2:]))
    elif l.startswith('## '): flush(); out.append('<h2>%s</h2>' % inline(l[3:]))
    elif l.strip() == '---': flush(); out.append('<hr>')
    elif re.match(r'^\d+\. ', l.strip()):
        if buf_p: flush()
        buf_ol.append(re.sub(r'^\d+\. ', '', l.strip()))
    elif l.strip().startswith('- '):
        if buf_p: flush()
        buf_li.append(l.strip()[2:])
    elif not l.strip(): flush()
    elif l.startswith('   ') and (buf_ol or buf_li):
        (buf_ol or buf_li)[-1] += ' ' + l.strip()
    else: buf_p.append(l.strip())
    i += 1
flush()
old = open('НАЧНИ ОТСЮДА.html', encoding='utf-8').read()
head = old[:old.index('</style></head><body><main>')+len('</style></head><body><main>')]
page = head + '\n' + '\n'.join(out) + '\n<p class="hint">Строку из серой рамки можно выделить одним щелчком и скопировать.</p>\n</main></body></html>'
open('НАЧНИ ОТСЮДА.html','w',encoding='utf-8').write(page)
print('h2:', page.count('<h2>'), 'pre:', page.count('<pre>'))
