#!/usr/bin/env python

### IMPORTS ###

import os
import sys
import time
import base64
import Queue
import time
import StringIO
from datetime import datetime, timedelta
from collections import defaultdict

# LIBRARIES
import numpy as np
import usb

yowsupdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yowsup', 'src')
sys.path.insert(0, yowsupdir)
escposdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'python-escpos')
sys.path.insert(0, escposdir)

# LOCAL

import Image
import escpos
from Yowsup.connectionmanager import YowsupConnectionManager
from Yowsup.Common.debugger import Debugger
# Debugger.enabled = True

### CONSTANTS ###

FONT = Image.open('font_tom_thumb.png').convert('L')

EVENT_LASTSEEN = 'lastseen'
EVENT_AVAILABLE = 'available'
EVENT_UNAVAILABLE = 'unavailable'

DOTS = 24
BAR_HEIGHT = 6
BAR_WIDTH = 4
BAR_MIN_WIDTH = 1
WIDTH = 512
BAR_INTERVAL  = timedelta(hours=1) / 4
BARS_PER_LINE = DOTS / BAR_HEIGHT
LINE_INTERVAL = BARS_PER_LINE * BAR_INTERVAL
LINES_PER_DAY = timedelta(days=1).total_seconds() / LINE_INTERVAL.total_seconds()


### FUNCTIONS ###
def verifySettings():
	if int(LINES_PER_DAY) != LINES_PER_DAY:
		raise Exception("No whole number of lines per day.")
	print 'Drawing %d dot bars every %s' % (BAR_HEIGHT, BAR_INTERVAL)
	print 'One line every %s, %d lines per day' % (LINE_INTERVAL, LINES_PER_DAY)


def loadConfigFile(configfile):
	""" Loads a yowsup style config file and returns
		values as a dictionary 
	"""
	config = {}
	if os.path.isfile(configfile):
		for line in open(configfile):
			# Remove bits after the comment marker
			line = line.split('#')[0].strip()
			# If anything is left
			if line:
				print line
				# Split by first equals sign
				key, val = line.split('=',1)
				config[key] = val
	return config


def findInterval(interval, now=datetime.now()):
	""" Returns the previous/next interval starting from 0:00 today.

		>>> findInterval(timedelta(minutes=15), now=datetime.strptime('20130625 20:33', '%Y%m%d %H:%M'))
		(datetime.datetime(2013, 6, 25, 20, 30), datetime.datetime(2013, 6, 25, 20, 45))
	"""
	count = timedelta(days=1).total_seconds() / interval.total_seconds()
	if int(count) != count:
		raise Exception("Interval is not a whole divisor of one day.")
	start = now.replace(hour=0, minute=0, second=0, microsecond=0)
	diff = now - start
	count = int(diff.total_seconds() // interval.total_seconds())
	return start + count * interval, start + (count + 1) * interval

def imageText(text, font=FONT, lw=4, lh=6, zoom=2):
	o = np.zeros((lh,len(text)*lw), dtype=np.uint8)
	f = np.array(FONT)
	per_row = f.shape[1] // lw
	for i,letter in enumerate(text):
		x, y = ord(letter) % per_row, ord(letter) // per_row
		x*=lw
		y*=lh
		o[0:lh, i*lw:(i+1)*lw] = f[y:y+lh, x:x+lw]
	o = Image.fromarray(o)
	if zoom != 1:
		o = o.resize((o.size[0]*zoom, o.size[1]*zoom), Image.NEAREST)
	return o

### CLASSES ###

class OnlinesClient(object):

	def __init__(self, config, keepAlive=False, sendReceipts=False, dryRun=False):
		self.sendReceipts = sendReceipts
		self.dryRun = dryRun
		self.config = config
			

		# Initialize
		connectionManager = YowsupConnectionManager()
		connectionManager.setAutoPong(keepAlive)
		self.signalsInterface = connectionManager.getSignalsInterface()
		self.methodsInterface = connectionManager.getMethodsInterface()

		# Configure the listeners
		self.signalsInterface.registerListener("auth_success", self.onAuthSuccess)
		self.signalsInterface.registerListener("auth_fail", self.onAuthFailed)
		self.signalsInterface.registerListener("disconnected", self.onDisconnected)
		
		self.signalsInterface.registerListener("message_received", self.onMessageReceived)

		self.signalsInterface.registerListener("presence_updated", self.onPresenceUpdated)
		self.signalsInterface.registerListener("presence_available", self.onPresenceAvailable)
		self.signalsInterface.registerListener("presence_unavailable", self.onPresenceUnavailable)


		# Create a queue so we can stash the incoming data somewhere
		self.events = Queue.PriorityQueue()
		# Dictionary of contacts with their names
		self.names = dict(config['jids'])
		self.contacts = [jid for jid, name in config['jids']]
		# A count of events for each interval for each contact
		self.tally = defaultdict(lambda: dict((jid, 0) for jid in self.contacts))
		self.printer = None
		self.connected = False
		self.lastline, self.nextline = findInterval(LINE_INTERVAL)
		self.nth = 0

	def start(self, username, password):
		""" Logs in and starts the main thread that checks and processes
			the print queue.
		"""
		self.username = username
		self.password = password
		self.connect()
		time.sleep(10)
		
		while True:
			# print "Connection status: %s" % self.connected
			if not self.connected:
				print "Not connected..."
				self.connect()
				time.sleep(10)
			
			try:
				if not self.dryRun:
					if self.printer is None:
						self.printer = escpos.printer.Usb(0x04b8,0x0202)
						print "Initialized printer."
					else:
						# We have a printer, but we still try to poke it
						# to provoke an error if it is disconnected.
						self.printer.set()
				# At this point we are sure to have a working printer, 
				# so we can pop something from the queue and print it.
				self.tallyEvents()
				self.printEvents()
				
			except (usb.core.USBError, escpos.exceptions.NotFoundError) as e:
				print type(e)
				print "Failed to initialize printer: %s" % e
				self.printer = None

			# Sleep to keep thread responsive
			time.sleep(10)

	def subscribeToContacts(self):
		self.methodsInterface.call('presence_sendAvailable')
		time.sleep(2)
		for jid in self.contacts:
			print 'Subscribing to %s' % jid
			self.methodsInterface.call('presence_request', (jid,))

	def connect(self):
		print "Connecting..."
		self.methodsInterface.call("auth_login", (self.username, self.password))

	def tallyEvents(self):
		""" Process the avalaible/unavailable event queue, and count how many
			occurred in each time interval """
		# Add the current interval to the tallies
		while True:
			try:
				# Pull an item from the queue
				t, jid, event = self.events.get(block=False)
				print t, jid, event, self.names.get(jid, 'unknown')
				if jid in self.contacts:
					interval = findInterval(BAR_INTERVAL, now=t)
					self.tally[interval][jid] += 1

			except Queue.Empty:
				break

	def printEvents(self):
		""" Process the tallies and print images """
		now = datetime.now()
		daystart, _ = findInterval(timedelta(days=1))
		self.nth = (daystart - self.lastline).total_seconds() // LINE_INTERVAL.total_seconds() 
		# print "Now %s, Nextline at %s" % (now, self.nextline)
		if now > self.nextline:
			# Collect the tallies from the last interval
			tallies = []
			for i in range(BARS_PER_LINE):
				start = self.lastline + i * BAR_INTERVAL
				end   = self.lastline + (i + 1) * BAR_INTERVAL
				if (start, end) not in self.tally:
					print "NOT FOUND",  (start, end)
				tallies.append(self.tally[(start, end)])
				
			# Sort the tallies by contact order:
			counts = [[c[o] for o in self.contacts] for c in tallies]
			if self.nth == 0:
				printnames = [self.names[jid] for jid in self.contacts]
			else:
				printnames = None
			if self.nth % 2 == 1:
				printdate = self.nextline
			else:
				printdate = None
			print np.array(counts)
			im = self.createImage(counts, printdate, printnames)
			
			# Cleanup the tally list:
			self.lastline, self.nextline = findInterval(LINE_INTERVAL, now=now)
			for interval in self.tally.keys():
				if interval[0] < self.lastline:
					print "%s is too old" % (interval,)
					del self.tally[interval]
			
			if self.printer:
				self.printer.image(im)
			else:
				im.save('zim%d.png' % time.time())


	def createImage(self, counts, date=None, texts=None):
		""" Creates an image out of a single line of tallies """
		if not len(counts) == DOTS/BAR_HEIGHT:
			raise Exception("Number of bars should be DOTS/BAR_HEIGHT")
		barw = WIDTH // len(self.contacts)
		startpos = [barw * i for i in range(len(self.contacts))]

		im = np.ones((DOTS, WIDTH), dtype=np.uint8) * 255
		for i, count in enumerate(counts):
			for j, c in enumerate(count):					
				ymin, ymax = i*BAR_HEIGHT, (i+1)*BAR_HEIGHT
				w = min(barw - 1, BAR_MIN_WIDTH + c * BAR_WIDTH)
				xmin, xmax = startpos[j], startpos[j] + w
				im[ymin:ymax, xmin:xmax] = 0
				# print texts on first line
				if texts and i == 0:
					t = np.array(imageText(texts[j]))
					th, tw = t.shape
					r = startpos[j] + 2
					im[0:th, r:r+tw] = t

		#Add date
		if date is not None:
			t = np.array(imageText(date.strftime('%Y%m%d %H:%M')))
			th, tw = t.shape
			im[-th:, -tw-1:-1] = t
		im[-1,::4] = 0
		im = Image.fromarray(im)
		return im

	def receipt(self, jid, messageId, wantsReceipt):
		""" Sends a read receipt if necessary 
		"""
		if wantsReceipt and self.sendReceipts:
			self.methodsInterface.call("message_ack", (jid, messageId))

	## SIGNAL HANDLERS ##
	def onAuthSuccess(self, username):
		print "Authed %s." % username
		self.methodsInterface.call("ready")
		self.connected = True
		self.subscribeToContacts()

	def onAuthFailed(self, username, err):
		print "Auth failed."
		print username, err
		self.connected = False

	def onDisconnected(self, reason):
		print "Disconnected because %s" %reason
		self.connected = False

	def onMessageReceived(self, messageId, jid, messageContent, timestamp, wantsReceipt, pushName):
		print messageId, jid, messageContent, timestamp, wantsReceipt, pushName
		self.receipt(jid, messageId, wantsReceipt)

	def onPresenceUpdated(self, jid, lastSeen):
		now = datetime.now()
		ago = timedelta(seconds=lastSeen)
		self.events.put((now - ago, jid, EVENT_LASTSEEN))

	def onPresenceAvailable(self, jid):
		now = datetime.now()
		self.events.put((now, jid, EVENT_AVAILABLE))

	def onPresenceUnavailable(self, jid):
		now = datetime.now()
		self.events.put((now, jid, EVENT_UNAVAILABLE))



if __name__ == '__main__':
	verifySettings()
	config = loadConfigFile('lebara.yowsupconfig')
	onlinesconfig = eval(open('dacosta.onlinesconfig').read())
	listener = OnlinesClient(onlinesconfig, keepAlive=True, sendReceipts=True, dryRun=False)
	if len(sys.argv) > 1 and sys.argv[1] == 'test':
		listener.createImage(np.array([[1,0,0,0,1,0,0],[0,3,0,0,2,0,0]]),
			datetime.now(),['thomas','frank','roos','rikke','iris','marijn','evelien']).save('test.png')
	listener.start(config['phone'], base64.b64decode(config['password']))

