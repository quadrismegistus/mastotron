SEEN=set()


import os,sys,socket,time,webbrowser,signal
path_app = os.path.realpath(__file__)
path_code = os.path.abspath(os.path.join(path_app,'..','..'))
path_codedir = os.path.abspath(os.path.join(path_code,'..'))
sys.path.insert(0,path_codedir)
import threading

from mastotron import *
from mastotron.imports import __version__ as vnum

from threading import Lock,Thread,Event

from flask import Flask, render_template, request, redirect, url_for, session, current_app
from flask_session import Session
from flask_socketio import SocketIO, send, emit
from mastodon import StreamListener
import os,time,sys,random
from engineio.async_drivers import eventlet
# from engineio.async_drivers import threading

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

namespace = 'mastotron.web'
seen_posts = set()
STARTED=None
new_urls = set()
new_msgs = []

@lru_cache
def Tron():
    obj = Mastotron()
    obj._logmsg = logmsg_tron
    return obj

def logmsg_tron(*x,**y):
    global new_msgs

    new_msgs.append(' '.join(str(xx) for xx in x))
    print('>>>',new_msgs[-1])

def logmsg(*x,**y):
    emit('logmsg',' '.join(str(xx) for xx in x))
    threading.Event().wait(0.1)
def logsuccess(x): emit('logsuccess',str(x))
def logerror(x): emit('logerror',str(x))

#####
HOSTPORTURL=f'http://{HOST}:{PORT}'

LINE1=f'MASTOTRON {vnum}'
LINE2=f'URL: {HOSTPORTURL}'
LINE3='(Visit this URL in your browser. It is now copied to your clipboard.)'
LOGO=r'''
                           _               _                             
  _ __    __ _     ___    | |_     ___    | |_      _ _    ___    _ _    
 | '  \  / _` |   (_-<    |  _|   / _ \   |  _|    | '_|  / _ \  | ' \   
 |_|_|_| \__,_|   /__/_   _\__|   \___/   _\__|   _|_|_   \___/  |_||_|  
_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""|_|"""""| 
"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-'"`-0-0-' 
'''
lwid=max(len(lstr) for lstr in LOGO.split('\n'))
WELCOME_MSG = f'''
{LOGO.center(lwid)}

{LINE1.center(lwid)}

{LINE2.center(lwid)}

{LINE3.center(lwid)}
'''


app = Flask(__name__, static_folder=path_static, template_folder=path_templates)
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(path_data, 'flask_session')
Session(app)
socketio = SocketIO(app, manage_session=False, async_handlers=False)
# socketio = SocketIO(app, manage_session=False, async_mode="threading")


@app.route("/")
@app.route("/hello/")
@app.route("/hello-vue/")
def postnet(): 
    acct=session.get('acct')
    if not acct or not Tron().user_is_init(acct): 
        return render_template('login.html', acct=acct, config_d=get_config())
    else:
        return render_template('postnet.html', acct=acct, config_d=get_config())

@app.route('/hello//flaskwebgui-keep-server-alive')
@app.route('/hello/flaskwebgui-keep-server-alive')
@app.route('/flaskwebgui-keep-server-alive')
def keepalive():
    return {'status':200}


def get_config(d={}):
    defaultd={
        'LIM_NODES_GRAPH':10,
        'LIM_NODES_STACK':25,
        'DARKMODE':1,
        'VNUM':vnum,
    }
    sessiond={k:v for k,v in session.items() if k and k[0]!='_'}
    outd = {**defaultd, **sessiond, **d}
    return outd

@socketio.event
def req_config(d={}):
    emit('res_config',get_config(d))

@socketio.event
def set_config(d):
    for k,v in d.items(): session[k]=v

@socketio.event
def set_acct_name(data):
    tron = Tron()
    acct = clean_account_name(data.get('acct'))
    if acct:
        session['acct'] = acct
        if not tron.user_is_init(acct):
            try:
                url = tron.user_auth_url(acct)
                logmsg('Please enter activation code')
                emit('get_auth_url', {'acct':acct,'url':url} )
            except Exception as e:
                un,server=parse_account_name(acct)
                emit('server_not_giving_code', {'server':server, 'acct':acct})
    else:
        emit('invalid_user_name', data)
        

@socketio.event
def do_login(data):
    tron = Tron()
    acct = data.get('acct')
    code = data.get('code')
    if acct and code:
        tron.api_user(acct, code=code, direct_input=False)
        if tron.user_is_init(acct):
            logmsg(f'{acct} logged in')
            emit('login_succeeded', dict(acct=acct))
        else:
            logmsg(f'{acct} NOT logged in')
            emit('login_failed', dict(acct=acct))


def get_acct_name(data={}): return session.get('acct')
def get_srvr_name(data={}): return parse_account_name(get_acct_name())[-1]



#########
# GRAPH #
#########

class NodeListener(StreamListener):
    def on_update(self, status):
        url = status.get('url')
        post = Post(url, **status)
        if post:
            new_urls.add(post)

@socketio.event
def start_updates(data={}):
    return
    global seen_posts, STARTED
    seen_posts = set()
    if not STARTED:
        acct = get_acct_name(data)
        print(f'\n>> listening for push updates on {acct}...')
        Tron().api_user(acct).stream_user(
            NodeListener(), 
            run_async=True
        )
        STARTED=True

@socketio.event
def get_pushes(data={}):
    global new_urls, new_msgs
    if new_msgs: logmsg(new_msgs.pop())

    new_posts = PostList(new_urls)
    new_urls = set()
    if new_posts:
        update_posts(
            new_posts, 
            omsg='push updated',
            force_push=True
        )

MAX_UPDATE=5

@socketio.event
def get_updates(data={}):
    global SEEN
    acct = get_acct_name()
    if not acct: return
    SEEN|=set(data.get('ids_now',[]))
    lim = data.get('lim') if data.get('lim') else get_config().get('LIM_NODES_STACK')
    force_push = data.get('force_push',False)

    lim=lim if lim<MAX_UPDATE else MAX_UPDATE
    iterr=Tron().timeline_iter(
        acct, 
        unread_only=data.get('unread_only',True),
        seen=SEEN,
        max_mins=60*24,
        lim=lim
    )
    for i,post in enumerate(iterr):
        if i>=lim: break
        update_posts(
            [post], 
            ids_done=SEEN, 
            force_push=force_push
        )
        SEEN|={p._id for p in post.allcopies}



def update_posts(tl, omsg='refreshed', emit_key='get_updates',ids_done=None,unread_only=True, force_push=False):
    if type(tl)!=PostList: tl=PostList(tl)
    if len(tl):
        # print('>',tl)
        tnet = tl.network()
        nx_g = tnet.graph(local_server=get_srvr_name())
        nx_g.remove_nodes_from(
            n 
            for n,d in list(nx_g.nodes(data=True))
            if (unread_only and d.get('is_read'))
            or (ids_done and d.get('id') in ids_done)
        )
        nodes = [d for n,d in nx_g.nodes(data=True)]
        edges = [d for a,b,d in nx_g.edges(data=True)]

        # print('ne',[d['id'] for d in nodes],[d['id'] for d in edges])

        omsg = f'{len(nodes)+len(edges)} new updates @ {get_time_str()}'
        if nodes or edges:
            odata = dict(nodes=nodes, edges=edges, logmsg=omsg, force_push=force_push)
            # for n in nodes: print('++',n['id'])
            emit(emit_key, odata)
            # time.sleep(0.1)
            threading.Event().wait(.1)
            return True
    
    # omsg = f'no new updates @ {get_time_str()}'
    # logmsg(omsg)
    return False

@socketio.event
def add_context(node_id):
    print('add_context',node_id)
    post = Post(node_id)
    if post:# unread_convo = PostList(p for p in post.convo if not p.is_read)
        convo = post.convo
        update_posts(convo[:LIM_TIMELINE], force_push=True)









@socketio.event
def set_darkmode(darkmode):
    key='DARKMODE'
    session[key] = int(darkmode)

@socketio.event
def set_in_session(dict):
    for k,v in dict.items():
        session[k]=v

@socketio.event
def mark_as_read(node_ids):
    print('mark_as_read', node_ids)
    for node_id in node_ids:
        post = Post(node_id)
        post.mark_read()











class OpenBrowser(Thread):
    def __init__(self):
        super(OpenBrowser, self).__init__()
    def notResponding(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        return sock.connect_ex((HOST, PORT))
    def run(self):
        while self.notResponding():
            # print('Did not respond')
            threading.Event().wait(0.1)
        # print('Responded')
        webbrowser.open_new(f'http://{HOST}:{PORT}/') 


def send_update(nodes=[], edges=[]):
    odata=dict(nodes=nodes, edges=edges)
    emit('get_updates', odata)
    return odata


def view(**kwargs):
    OpenBrowser().start()

def mainview(**kwargs):
    view(**kwargs)
    main(**kwargs)

def main(debug=False, **kwargs): 
    pyperclip.copy(HOSTPORTURL)
    print(WELCOME_MSG)
    return socketio.run(
        app, 
        debug=debug, 
        # allow_unsafe_werkzeug=True,
        port=PORT,
        host=HOST
    )

if __name__=='__main__': mainview(debug=False)