from bs4 import BeautifulSoup
from cum import config, exceptions, output
from cum.scrapers.base import BaseChapter, BaseSeries, download_pool
from functools import partial
from mimetypes import guess_type
from urllib.parse import urljoin, urlparse
import concurrent.futures
import re
import requests


class MangadexSeries(BaseSeries):
    """Scraper for mangadex.org.

    Some examples of chapter info used by Mangadex (matched with `name_re`):
        Vol. 2 Ch. 18 - Strange-flavored Ramen
        Ch. 7 - Read Online
        Vol. 01 Ch. 001-013 - Read Online
        Vol. 2 Ch. 8 v2 - Read Online
        Oneshot
    """
    url_re = re.compile(r'(?:https?://mangadex\.(?:org|com))?/[^/]+/([0-9]+)')
    chapter_re = re.compile(r'Ch\. ?([A-Za-z0-9\.\-]*)(?: v[0-9]+)?(?: - (.*))')

    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)
        id = self.url_re.match(self.url).group(1)
        r = requests.get("https://mangadex.org/api/?id=%s&type=manga" % (id, ))
        self.data = r.json()
        self.chapters = self.get_chapters()

    def get_chapters(self):
        chapters = []
        
        for chapter_id, d in self.data.get("chapter", {}).items():
            if d["lang_code"] not in ("gb", "us"):
                continue
            url = "https://mangadex.org/chapter/%s" % (chapter_id, )
            chapter_no = d["chapter"]
            if self.chapter_re.match(chapter_no):
                chapter_no = self.chapter_re.match(chapter_no).group(1)
            
            c = MangadexChapter(url=url,
                                name=self.name,
                                alias=self.alias,
                                chapter=chapter_no,
                                groups=[ d["group_name"] ],
                                title=d["title"].strip() or None)
            chapters.append(c)
        
        return chapters

    @property
    def name(self):
        return self.data["manga"]["title"]


class MangadexChapter(BaseChapter):
    url_re = re.compile(
        r'(?:https?://mangadex\.(?:org|com))?/chapter/([0-9]+)')
    uses_pages = True

    @staticmethod
    def _reader_get(url, page_index=0):
        # page_index is ignored, we can get all pages at once
        id = MangadexChapter.url_re.match(url).group(1)
        url = "https://mangadex.org/api/?id=%s&type=chapter" % (id,)
        return requests.get(url)

    def available(self):
        self.r = self.reader_get(1)
        try:
            return len(self.r.json()["page_array"]) > 0
        except Exception as e:
            return False

    def download(self):
        if getattr(self, 'r', None):
            r = self.r
        else:
            r = self.reader_get(1)
        
        data = r.json()
        chapter_hash = data["hash"]
        server = data["server"]
        if server.startswith("/data/"):
            server = "https://mangadex.org" + server
        pages = data["page_array"]
        
        files = [None] * len(pages)
        futures = []
        last_image = None
        with self.progress_bar(pages) as bar:
            for i, page in enumerate(pages):
                if guess_type(page)[0]:
                    image = server + chapter_hash + '/' + page
                else:
                    print('Unkown image type for url {}'.format(page))
                    raise ValueError
                print ("#{#{}}", image)
                r = requests.get(image, stream=True)
                if r.status_code == 404:
                    r.close()
                    raise ValueError
                fut = download_pool.submit(self.page_download_task, i, r)
                fut.add_done_callback(partial(self.page_download_finish,
                                              bar, files))
                futures.append(fut)
                last_image = image
            concurrent.futures.wait(futures)
            self.create_zip(files)

    def from_url(url):
        r = MangadexChapter._reader_get(url)
        series_url = "https://mangadex.org/title/%s" % (r.json()["manga_id"],)
        series = MangadexSeries(series_url)
        for chapter in series.chapters:
            parsed_chapter_url = ''.join(urlparse(chapter.url)[1:])
            parsed_url = ''.join(urlparse(url)[1:])
            if parsed_chapter_url == parsed_url:
                return chapter

    def reader_get(self, page_index):
        return self._reader_get(self.url, page_index)

