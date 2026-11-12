from html.parser import HTMLParser
from lab import fetch

class CellText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells=[]
        self.stack=[]

    def handle_starttag(self,tag,attrs):
        if tag in ('th','td'):
            self.stack.append([])

    def handle_data(self,data):
        if self.stack:
            self.stack[-1].append(data)

    def handle_endtag(self,tag):
        if tag in ('th','td') and self.stack:
            self.cells.append(''.join(self.stack.pop()).strip())

def inspect(base,fixture):
    status,headers,body=fetch(base+'/v1')
    parser=CellText()
    parser.feed(body.decode('utf-8'))
    return {'状态':status,'单元格文本':parser.cells}
