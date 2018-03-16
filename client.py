#!/usr/bin/python
#coding:utf-8

import socket
import select
import threading
import zlib
import itertools
import signal
import sys
import logging
import time

SERVER = ("11.22.33.44",8888)
SERVERALIVE = ("11.22.33.44",8889)
LISTENPORT = ("127.0.0.1",5115)
listens = []
host2server = {}
server2host = {}
KEY = 'yourkey'
ISQUIT = 0
tdLock = threading.Lock()
tdCondition = threading.Condition()
logger = logging.getLogger("CLIT")

def proxyRunning():
	signal.signal(signal.SIGINT, signal_handler)
	client2proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	client2proxy.bind(LISTENPORT)
	listens.append(client2proxy)
	client2proxy.listen(5)
	aliveSocks = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	t = threading.Thread (target=doKeepAlive, args=(aliveSocks,))
	t.start()
	logger.info("Client is running...")
	while 1:
		logger.debug ("HST2SVR len:", len(host2server))
		logger.debug ("SVR2HST len:", len(server2host))
		logger.debug ("Listen len:", len(listens))
		lrlist,lwlist,lelist =  select.select(listens, [],listens,1)
		for r in lrlist:
			if r == client2proxy: #新连接进来
				conn, addr = r.accept()
				listens.append(conn)
				logger.debug ("New Connection Add!")
				#将该条连接标记为待连接状态(server为空)并且加入关联字典host2server
				host2server[conn] = None
			else:
				#如果是已经有的连接，先判断是否为server传入，是则直接转发，
				#不是则创建与server的连接，并且加入关联字典localRemoteSockets1，
				#并且加入Remote列表与O2IproxySocket
				#没有找到则视为一条新的传入连接，创建连接加入listens队列，
				#并加入Remote列表与O2IproxySocket。
				if isServerSocket(r): #传入流量
					try:
						buf = recvDataBlock(r)
					except socket.error as e:
						logger.error ("%s",e)
						buf = ''
					if not buf:
						r.close()
						logger.debug ("111 %s", r)
						listens.remove(r)
						if server2host[r] in listens:
							listens.remove(server2host[r])
						if server2host[r] in lrlist:
							lrlist.remove((server2host[r]))
						rmSocket1(r)
					else:
						xbuf = unzipXorData(buf)
						try:
							server2host[r].sendall(xbuf)
						except socket.error as e:
							logger.error ("Send data to Broswer error! %s", e)
							r.close()
							logger.debug ("222 %s", r)
							listens.remove(r)
							if server2host[r]  in listens:
								listens.remove(server2host[r])
							if server2host[r] in lrlist:
								lrlist.remove(server2host[r])
							rmSocket1(r)
				else: #传出流量
					try:
						rHeadData = r.recv(4096)
					except socket.error as e:
						rHeadData = ''
						logger.error ("Broswer socket error: %s", e)
					logger.debug (rHeadData)
					if not rHeadData: #连接被对方关闭
						#处理连接池
						r.close()
						logger.debug ("333 %s", r)
						if r in listens:
							listens.remove(r)
						if host2server[r] in listens:
								listens.remove(host2server[r])
						if host2server[r] in lrlist:
								lrlist.remove(host2server[r])
						rmSocket1(r)
					elif host2server[r] == None: #连接服务器
						proxy2server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
						socket.setdefaulttimeout(10)
						t = threading.Thread (target=doConnect, args=(SERVER,proxy2server, r, rHeadData))
						t.start()
					else:
						xrHeadData = zipXorData(rHeadData)+'1000'
						try:
							host2server[r].sendall(xrHeadData)
						except socket.error as e:
							logger.error ("Send data to server error! %s", e)
							r.close()
							logger.debug ("444 %s", r)
							if r in listens:
								listens.remove(r)
							if host2server[r] in listens:
								listens.remove(host2server[r])
							if host2server[r] in lrlist:
								lrlist.remove(host2server[r])
							rmSocket1(r)
		if lelist:
			logger.debug (lelist)
			logger.error ("ERROR,QUIT!")
			for i in listens:
				i.close()
			break
		
def doConnect (tgHost, outSocket, inSocket, data):
	if tgHost is None or outSocket is None:
		return
	else:
		tdLock.acquire()
		logger.debug ("Connect to:", tgHost)
		tdLock.release()
		try:
			outSocket.connect(tgHost)
		except socket.error as e:
			tdLock.acquire()
			logger.error ("CONNECT ERROR: %s", (e, tgHost))
			tdLock.release()
			del outSocket
			return
		if inSocket in host2server.keys():
			host2server[inSocket] = outSocket
			server2host[outSocket] = inSocket
			listens.append(outSocket)
		else: #等我连接上了，浏览器都断开了？
			outSocket.close()
			logger.debug ("555 %s", outSocket)
			del outSocket
			logger.debug ("Connect Closed by Broswer...")
			return
		xdata = zipXorData(data)+'1000'
		outSocket.sendall(xdata)
		logger.debug ("Connect Thread exit...")
		return
			
def doKeepAlive(s):
	global ISQUIT
	dt = 'OnLine'
	time.sleep(6)
	while 1:
		tdCondition.acquire()
		if ISQUIT:
			tdCondition.release()
			s.close()
			break
		s.sendto(dt, SERVERALIVE)
		tdCondition.wait(48)
		tdCondition.release()
			
def isServerSocket(s):
	if s in server2host.keys():
		return True
	else:
		return False

def rmSocket1 (s):
	if s in host2server.keys():
		if host2server[s] is not None:
			host2server[s].close()
			logger.debug ("del:", host2server[s])
			del server2host[host2server[s]]
		del host2server[s]
		return
	if s in server2host.keys():
		if server2host[s] is not None:
			server2host[s].close()
			logger.debug ("server2host[s]:%s", server2host[s])
			logger.debug ("HST2SVR[s]:%s", host2server)
			if server2host[s] in host2server.keys():
				del host2server[server2host[s]]
		del server2host[s]
		return

def xor(s, key):
	key = key * (len(s) / len(key) + 1)
	return ''.join(chr(ord(x) ^ ord(y)) for (x,y) in itertools.izip(s, key))

def zipXorData(data):
	zdata = zlib.compress(data,4)
	xdata = xor(zdata, KEY)
	l = len(xdata)
	if l>9999:
		return None
	n = '%04d' %l
	return 'LN' + n + xdata

def unzipXorData(data):
	xdata = xor(data, KEY)
	zdata = zlib.decompress(xdata)
	return zdata

#+--+----+--------------+----+
#|LN|XXXX|     DATA     |1000|
#+--+----+--------------+----+
def recvDataBlock (socket):
	data = ''
	head = socket.recv(6)
	if not head:
		return None
	if len(head) < 6:
		t= socket.recv(6-len(head))
		head = head+t
	flag = head[:2]
	l = 0
	k = 0
	logger.debug ("Flag:", head)
	if flag == 'LN':
		l = int(head[2:])
		k = l
	else:
		logger.error ("Bad data Block!!!")
		return None
	logger.debug ("len is %d", l)
	while 1:
		t = socket.recv(l+4)
		if not t:
			return None
		data = data + t
		if len(data) >= k+4:
			break
		l = l-len(t)
	data = data[:len(data)-4]
	return data		
		
def signal_handler(signal, frame):
	global ISQUIT
	print "Proxy is quitting now..."
	ISQUIT = 1
	tdCondition.acquire()
	tdCondition.notify()
	tdCondition.release()
	for i in threading.enumerate():
		if i is not threading.currentThread():
			i.join()
	for i in listens:
		i.close()
	print "Quit"
	logging.shutdown()
	sys.exit(0)

def init_loger():
	logger.setLevel(logging.INFO)
	handler = logging.FileHandler('client.log')
	handler.setLevel(logging.INFO)
	formatter = logging.Formatter('%(asctime)s-%(levelname)s-%(message)s')
	handler.setFormatter(formatter)
	logger.addHandler(handler)

if __name__ == "__main__":
	init_loger()
	proxyRunning()

