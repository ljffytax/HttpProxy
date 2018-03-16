#!/usr/bin/python2.7
#coding:utf-8

import socket
import select
import threading
import zlib
import itertools
import sys
import logging
import time
import copy

LISTENPORT = ("0.0.0.0",8888)
ALIVEPORT = ("0.0.0.0",8889)
KEY = 'yourkey'
SSL_TUNNEL_OK = '''HTTP/1.1 200 Connection Established\r\nProxy-Connection: close\r\n\r\n'''
clientIP = {}
listens = []
localRemoteSockets1 = {} #{proxyInSocket:[(proxyOutSocket,webHost),],}
#映射传入路径
O2IproxySockets = {} #{outSockt:inSocket,}
logger = logging.getLogger("rootloger")

def serverRunning():
	client2proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	client2proxy.bind(LISTENPORT)
	listens.append(client2proxy)
	client2proxy.listen(5)
	aliveSocks = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	aliveSocks.bind(ALIVEPORT)
	t = threading.Thread (target=doKeepAlive, args=(aliveSocks,))
	t.start()
	t = threading.Thread (target=doCheckOffLine)
	t.start()
	while 1:
		lrlist,lwlist,lelist =  select.select(listens, [],listens,1)
		for r in lrlist:
			if r == client2proxy: #新连接进来,是否是已有的客户端?
				conn, addr = r.accept()
				listens.append(conn)
				if addr[0] not in clientIP:
					clientIP[addr[0]] = 1
					logger.info("New client connected IP: %s",addr[0])
				#将该条连接标记为待连接状态(Remote为空)并且加入关联字典localRemoteSockets1
				localRemoteSockets1[conn] = []
			else:
				#如果是已经有的连接，先判断是否为RemoteSocket，是则直接转发，
				#不是则解析每一个HTTP头，从中找出webHost并在Remote列表中查找对应的proxyOutSocket，找到则转发。
				#没有找到则视为一条新的传出连接，创建连接加入listens队列，并加入Remote列表与O2IproxySocket。
				if isOutSocket(r):
					try:
						buf = r.recv(4096)
					except socket.error as e:
						logger.error("Recive data from server error:%s", e)
					if not buf:
						r.close()
						listens.remove(r)
						rmSocket1(r)
					else:
						xbuf = zipXorData(buf)+'1000'
						try:
							O2IproxySockets[r].sendall(xbuf)
						except socket.error as e:
							logger.error("Send data to Broswer error! %s", e)
							r.close()
							listens.remove(r)
							rmSocket1(r)
				else:
					try:
						xrHeadData = recvDataBlock(r)
						if xrHeadData:
							rHeadData = unzipXorData(xrHeadData)
						else:
							rHeadData = None
					except socket.error as e:
						logger.error("Broswer socket error:%s", e)
					#print rHeadData
					if not rHeadData: #连接被对方关闭
						#处理连接池
						if r in localRemoteSockets1.keys():
							for skt in localRemoteSockets1[r]: #关闭与之相关的传出SOCKET
								#print "CLOSE", skt[0]
								skt[0].close()
								#print listens
								if skt[0] in listens:
									listens.remove(skt[0])
								if skt[0] in lrlist:
									lrlist.remove(skt[0])
							rmSocket1(r)
							#del localRemoteSockets1[r]
							if r in listens:
								listens.remove(r)
							r.close()
						else:
							#Never in here
							#print "HaHa??", r
							listens.remove(r)
							r.close()
							#rmSocket1(r)
						
					else:
						rHost, rPort = getRemoteHost(rHeadData)
						#print 'Host:Port', rHost, rPort
						if rHost is not None and rPort is not None:
							rmt  = getRemoteSocket1 (r,rHost)
							if rmt is not None:
								#doProxy(rmt, r, 4096)
								#print "RTM:", rmt
								rmt.sendall(rHeadData)
							else:
								proxy2server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
								socket.setdefaulttimeout(10)
								t = threading.Thread (target=doConnect, args=((rHost, int(rPort)),proxy2server, r, rHeadData))
								t.start()
						else:
							#Maybe SSL
							if localRemoteSockets1[r]:
								try:
									localRemoteSockets1[r][0][0].sendall(rHeadData)
								except socket.error as e:
									logger.error( "Send data to server error: %s", e)
									if r in localRemoteSockets1.keys():
										for skt in localRemoteSockets1[r]: #关闭与之相关的传出SOCKET
											#print "CLOSE", skt[0]
											skt[0].close()
											#print listens
											if skt[0] in listens:
												listens.remove(skt[0])
											if skt[0] in lrlist:
												lrlist.remove(skt[0])
									r.close()
									rmSocket1(r)
									if r in listens:
										listens.remove(r)
							else:
								r.close()
								rmSocket1(r)
								listens.remove(r)
							
		if lelist:
			print lelist
			logger.error ("ERROR,QUIT!")
			for i in listens:
				i.close()
			break
		
def doConnect (tgHost, outSocket, inSocket, data):
	if tgHost is None or outSocket is None:
		return
	else:
		try:
			outSocket.connect(tgHost)
		except socket.error as e:
			#print "CONNECT ERROR:", e
			del outSocket
			return
		#等我连接上了，浏览器都断开了？
		if inSocket in localRemoteSockets1.keys():
			localRemoteSockets1[inSocket].append((outSocket,tgHost[0]))
		else:
			outSocket.close()
			del outSocket
			#print "Connect Closed by Broswer..."
			return
		listens.append(outSocket)
		O2IproxySockets[outSocket] = inSocket
		if tgHost[1] == 443:
			#print "SSL open OK"
			#print localRemoteSockets1[inSocket]
			inSocket.sendall (zipXorData(SSL_TUNNEL_OK)+'1000')
		else:
			outSocket.sendall(data)
		#print "Connect Thread exit..."
		return
			
def doKeepAlive(s):
	dt = ''
	while 1:
	# 接收数据:
		dt, addr = s.recvfrom(1024)
		if addr[0] in clientIP.keys():
			clientIP[addr[0]] += 1
		else:
			logger.info ("Bad packges from IP: %s", addr[0])
		
def doCheckOffLine():
	ips = copy.copy(clientIP)
	while 1:
		time.sleep(3*60)
		for k in ips.keys():
			if clientIP[k] == ips[k]: #Off Line
				logger.info ("Client off line IP:%s", k)
				del clientIP[k]
		ips = copy.copy(clientIP)

def isOutSocket(s):
	if s in O2IproxySockets.keys():
		return True
	else:
		return False
	
def getRemoteSocket1 (r,rHost):
	#localRemoteSockets1 = {proxyInSocket:[(proxyOutSocket,webHost),],}
	if localRemoteSockets1[r]:
		for i in localRemoteSockets1[r]:
			if i[1] == rHost:
				return i[0]
		return None
	else:
		return None
	
def rmSocket1 (s):
	#localRemoteSockets1 = {proxyInSocket:[(proxyOutSocket,webHost),],}
	#O2IproxySockets = {outSockt:inSocket,}
	if s in localRemoteSockets1.keys(): #入端接口
		del localRemoteSockets1[s]
		for k in O2IproxySockets.keys():
			if O2IproxySockets[k] == s:
				del O2IproxySockets[k]
	else:
		l = localRemoteSockets1[O2IproxySockets[s]]
		for i in l:
			if i[0] == s:
				l.remove(i)
				break
		del O2IproxySockets[s]

def getRemoteHost (headData):
	'''接收http请求'''
	request = ''
	got_header = False
	headers = {}
	request = headData
	if not got_header and '\r\n\r\n' in request:
		got_header = True
		request_header = request.split('\r\n\r\n')[0] + '\r\n\r\n'
		header_length = len(request_header)
		host, port = parserRequestHeaders(request_header)
		return host, port
	else:
		return None, None

def parserRequestHeaders(request_headers):
	'''解析http请求头,返回（host, port, method, uri, headers）'''
	lines = request_headers.strip().split('\r\n')
	try:
		'''解析请求方法和uri'''
		line0 = lines[0].split(' ')
		method = line0[0].upper()
		uri = line0[1]
	
		'''解析其他header'''
		headers = {}
		for i in range(1,len(lines)):
			line= lines[i].split(':')
			key = line.pop(0)
			if key == 'Host' and len(line) >= 2: #host:port
				line[0] = line[0] + ':'
			value = ''.join(line)
			headers[key] = value.strip()

		'''处理目标主机和端口'''
		if method in ['CONNECT']:
			target_host_and_port = uri.split(':')
		else:
			target_host_and_port = headers['Host'].split(':')
		if len(target_host_and_port)==1:
			target_host = target_host_and_port[0]
			if method in ['CONNECT']:
				target_port = 443
			else:
				target_port = 80
		else:
			target_host = target_host_and_port[0]
			target_port = int(target_host_and_port[1].strip())
	except Exception, e: 
		#logging.warning(str(type(e))+' '+str(e)+' err')
		#return None,None,None,None,None
		return None,None
	#return target_host, target_port, method, uri, headers
	return target_host, target_port

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
	#print "Flag:", head
	if flag == 'LN':
		l = int(head[2:])
		k = l
	else:
		logger.error ("Bad data Block!!!")
		return None
	#print "len is ", l
	while 1:
		t = socket.recv(l+4)
		#print "T is :", len(t)
		if not t:
			return None
		data = data + t
		if len(data) >= k+4:
			break
		l = l-len(t)
	#print data
	data = data[:len(data)-4]
	return data	

def init_loger():
	logger.setLevel(logging.INFO)
	handler = logging.FileHandler('/var/log/pythonserverProxy.log')
	handler.setLevel(logging.INFO)
	formatter = logging.Formatter('%(asctime)s-%(levelname)s-%(message)s')
	handler.setFormatter(formatter)
	logger.addHandler(handler)

if __name__ == "__main__":
	init_loger()
	serverRunning()

