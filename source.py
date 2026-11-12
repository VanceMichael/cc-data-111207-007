class Source:
    def __init__(self,fixture):
        self.fixture=fixture

    def handle(self,path,headers):
        page=self.fixture['pages'].get(path)
        if page is None:
            return 404,{},b''
        return 200,{'Content-Type':'text/html; charset=utf-8'},page.encode()
