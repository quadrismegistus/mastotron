from .imports import *

def Tron():
    return Mastotron()

CACHES = {}
APIS = {}

class Mastotron():
    def __init__(self):
        global CACHES, API_SERVERS

        self._api = APIS
        self._posts = {}
        self._seen_urls = set()
        self._caches = CACHES
    
    def _get_path_api_auth(self, server):
        return os.path.join(
            path_data, 
            'mastodon_clients',
            get_server_name(server)+'.secret'
        )
    def _get_path_user(self, account_name):
        un,server = parse_account_name(account_name)
        return os.path.join(
            path_data,
            f'{un}@{server}'
        )
        
    def _get_path_user_auth(self, account_name):
        return os.path.join(
            self._get_path_user(account_name),
            f'usercred.secret'
        )

    def api(self, server_or_account):
        return self.api_server(server_or_account) if not '@' in server_or_account else self.api_user(server_or_account)

    def api_server(self, server):
        server = get_server_name(server)
        path_client_secret = self._get_path_api_auth(server)

        if not server in self._api:
            odir=os.path.dirname(path_client_secret)
            if not os.path.exists(odir): os.makedirs(odir)
            
            Mastodon.create_app(
                f'mastotron_{server.replace(".","")}',
                api_base_url = f'https://{server}/',
                to_file = path_client_secret
            )

            self._api[server] = Mastodon(client_id = path_client_secret)
        return self._api[server]

    
    def user_is_init(self, account_name):
        path_user_secret = self._get_path_user_auth(account_name)
        return os.path.exists(path_user_secret)

    def api_user(self, account_name, code=None):
        un,server = parse_account_name(account_name)
        path_user_secret = self._get_path_user_auth(account_name)
        if not os.path.exists(path_user_secret):
            odir = os.path.dirname(self.path_user_secret)
            if not os.path.exists(odir): os.makedirs(odir)
            
            api = self.api(server)
        
            if not code:
                url=api.auth_request_url()
                webbrowser.open(url)
                code = input('Paste the code from the browser:\n')
            
            api.log_in(code = code, to_file = path_user_secret)
            return api
        else:
            return Mastodon(access_token = path_user_secret)
    
    @cached_property
    def db(self): 
        return TinyDB(path_tinydb)
    
    def cache(self, dbname='cachedb'):
        if not dbname in self._caches:
            self._caches[dbname] = SqliteDict(path_db+'.'+dbname, autocommit=True)
        return self._caches.get(dbname)
    
    def status(self, url):
        res = {}
        cache = self.cache('status')
        # with self.cache('status') as cache:
        if url in cache:
            # log.debug(f'getting {url} from cache')
            return cache[url]
        else:
            server_name = get_server_name(url)
            status_id = get_status_id(url)
            api = self.api_server(server_name)
            log.debug(f'getting {server_name}\'s {status_id} from API')
            try:
                res = api.status(status_id)
                # except MastodonNotFoundError as e:
                log.debug(f'got {url} from API')
                try:
                    cache[url] = res
                except AttributeError:
                    pass
            except Exception as e:
                print(f'!! {e}: {url} !!')
                res = {}
        return res

    def get_uri(self, url_or_uri):
        print('????',url_or_uri)
        uri = url_or_uri
        if not uri: 
            return
        orig_server = get_server_name(uri)
        cache=self.cache('url_to_uri')
        uri2 = cache.get(uri)
        uri3 = to_uri(uri2 if uri2 else uri)
        o=uri3 if uri3 else (uri2 if uri2 else uri)
        cache[uri] = o
        cache[o+'__in__'+orig_server]=o
        print(uri,'-->',o)
        print(o+'__in__'+orig_server,'-->',o)
        return o
        
        

    def post(self, url_or_uri, **post_d):
        post = None
        if not url_or_uri: return

        # ensure appropriate format
        uri = self.get_uri(url_or_uri)
        print(['uri?',uri,url_or_uri])
        if not uri: return
        
        # if cached
        if uri in self._posts: return self._posts[uri]

        # get from db?
        db = TronDB()
        post_from_db = db.get_post(uri)
        if post_from_db: 
            # log.debug(f'getting {uri} from trondb')
            post = PostModel({**post_from_db, **post_d})

        if not post:
            # get from status?
            if not post_d: # ok to trust custom dicts ?
                post_d = self.status(uri)
            
            if post_d: 
                # print(post_d.keys())
                uri2 = post_d.get('url',uri)
                uri3 = self.get_uri(uri2)
                # if uri3 and uri2 and uri2 != uri3:
                #     cache=self.cache('url_to_uri')
                #     cache[uri] = uri2
                #     uri = uri2

                # print([uri,uri2,uri3])

                # log.debug('saving post_d into trondb')
                post = PostModel({**post_d, '_id':uri3 if uri3 else uri2})
                db.set_post(post.data)

        if post:
            self._posts[uri] = post

        return post
            

    def status_context(self, uri):
        # with self.cache('context') as cache:
        cache = self.cache('context')
        if not uri in cache:
            server,uname,status_id = get_server_account_status_id(uri)
            try:
                cache[uri] = self.api_server(server).status_context(status_id)
            except Exception as e:
                log.error(e)
                return {}
                
        return cache[uri]

    
    def latest(self, **kwargs):
        return PostList(list(self.latest_iter(**kwargs)))

    def latest_iter(self, mins_ago=60, unread_only=True):
        now = int(round(datetime.now().timestamp()))
        then = now - (mins_ago * 60)
        
        func=TronDB().since if not unread_only else TronDB().since_unread
        for post in func(then):
            post = PostModel(dict(post))
            if post.is_valid:
                yield post


    def latest_n(self, n=10):
        uris = [row['uri'] for row in self.db.all()[-n:]]
        return PostList([self.post(uri) for uri in uris])
    
    def timeline_iter(self, account_name, timeline_type='local', unread_only=True, lim=50, lim_iter=5):
        api = self.api_user(account_name)
        try:
            timeline = api.timeline(timeline=timeline_type)
            num_yielded = 0
            num_looped = 0
            while timeline:
                num_looped+=1
                if num_looped>lim_iter: break

                for post_d in timeline:
                    pprint(post_d)
                    stopx
                    # uri = to_uri(post_d.url if post_d.url else post_d.uri)
                    uri = post_d.url if post_d.url else post_d.uri
                    print('uri!!',uri)
                    if uri:# and uri not in seen_urls:
                        # seen_urls.add(uri)
                        post = self.post(uri, **dict(post_d))
                        if post: 
                            if not unread_only or not post.is_read:
                                yield post
                                num_yielded+=1
                                if lim and num_yielded>=lim: 
                                    timeline = None
                                    break
                # keep going
                if timeline is None: break
                try:
                    timeline = api.fetch_previous(timeline)
                except MastodonNetworkError as e:
                    log.error(e)
                    print(e)
                    api = self.api_user(account_name)
                    try:
                        timeline = api.fetch_previous(timeline)
                    except MastodonNetworkError as e:
                        print(e)
                        timeline = None
        except MastodonNetworkError as e:
            print(e)
            log.error(e)
            pass

        # print(num_looped, num_yielded, timeline)
                


    def timeline(self, account_name, n=10, **y):
        iterr = self.timeline_iter(account_name, **y)
        res = list(islice(iterr, n))
        return PostList(res)
    

        




