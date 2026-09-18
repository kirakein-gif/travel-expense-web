from urllib.request import Request, urlopen

URLS = [
"https://www.me.go.kr/home/web/board/list.do?boardCategoryId=39&boardMasterId=1&condition.createDeptCode=&condition.createDeptName=&condition.createId=&condition.fromDate=&condition.hideCate=&condition.proxyParam1=&condition.proxyParam2=&condition.proxyParam3=&condition.toDate=&decorator=&initialLoad=&maxIndexPages=10&maxPageItems=10&menuId=286&order=&pagerOffset=0&proxyListPath=&proxyReadPath=&searchKey=&searchValue=",
"https://www.me.go.kr/home/mob/board/list.do?boardCategoryId=&boardMasterId=39&maxIndexPages=5&maxPageItems=10&menuId=290&pagerOffset=0&searchKey=&searchValue=",
"https://www.me.go.kr/home/web/newsRead.do?boardId=1874650&boardMasterId=939&menuId=10607",
]
for url in URLS:
    try:
        req=Request(url,headers={"User-Agent":"Mozilla/5.0","Accept-Language":"ko-KR,ko;q=0.9"})
        with urlopen(req,timeout=30) as res:
            text=res.read().decode("utf-8",errors="replace")
            print("OK",res.status,len(text),url)
            print("charge", "충전" in text, "325.6", "325.6" in text, "title", "전기차 공공 충전 요금 체계 개편" in text)
    except Exception as e:
        print("FAIL",url,repr(e))
