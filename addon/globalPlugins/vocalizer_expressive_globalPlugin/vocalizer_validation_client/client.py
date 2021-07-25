import ctypes
import os
import os.path
import sys
# Try importing urllib and json modules, if not available use the bundled one.
try:
	import json
	import urllib2
except ImportError:
	path = os.path.dirname(__file__)
	if isinstance(path, unicode):
		path = path.encode("mbcs")
	sys.path.insert(0, path)
	try:
		import json
		import urllib2
	finally:
		sys.path.remove(path)

import ssl
from logHandler import log

from constants import *


class VocalizerValidationClient(object):

	def __init__(self, emailOrCode, password=None, useActivationCode=False):
		log.debug("Creating vocalizer validation client for %s", emailOrCode)
		self._emailOrCode = emailOrCode
		self._userId = None
		self._useActivationCode = useActivationCode
		self._headers = {'Content-type' : 'application/json'}
		if not useActivationCode:
			self._headers['Authorization'] = " ".join(("basic",
				("%s:%s" % (emailOrCode, password)).encode("base64").strip()))

	def _do_request(self, url, data=None, expectedStatus=200):
		if data is not None:
			data = json.dumps(data)
		request = urllib2.Request(url, data=data, headers=self._headers)
		try:
			response = urllib2.urlopen(request)
		except urllib2.URLError as e:
			if len(e.args) > 0 and isinstance(e.args[0], ssl.SSLError) and e.args[0].reason == u"CERTIFICATE_VERIFY_FAILED":
				_updateWindowsRootCertificates()
				# retry the request
				response = urllib2.urlopen(request)
			else:
				raise 
		return json.load(response)

	def getLicenseInfo(self):
		log.debug("Getting license info for %s", self._emailOrCode)
		url = API_URL + "/info/" + self._emailOrCode
		return self._do_request(url)

	def activateLicense(self):
		assert not self._useActivationCode
		log.debug("Activating license for %s", self._emailOrCode)
		url = API_URL + "/activate/%d" % self.userId
		return self._do_request(url, data="")

	def renew(self, number, token):
		log.debug("Renewing license for %s", self._emailOrCode)
		if self._useActivationCode:
			url = API_URL + "/unregistered/renew/%s" % self._emailOrCode
		else:
			url = API_URL + "/renew/%d" % self.userId
		data = {"number" : number, "token" : token}
		return self._do_request(url, data)

	def registerLicenseFromActivationCode(self, code, number):
		assert not self._useActivationCode
		url = API_URL + "/unregistered/registerLicenseFromActivationCode/" + code
		data = {"number" : number}
		return self._do_request(url, data)

	def disable(self, number):
		assert not self._useActivationCode
		log.debug("Disabling license for %s", self._emailOrCode)
		url = API_URL + "/disable/%d" % self.userId
		data = {"number" : number}
		return self._do_request(url, data)

	def _getUserId(self):
		assert not self._useActivationCode
		if self._userId is None:
			info = self.getLicenseInfo()
			self._userId = info['userId']
		return self._userId

	@property
	def userId(self):
		return self._getUserId()


# Shamefully copied from NVDA's source code.
# These structs are only complete enough to achieve what we need.
class CERT_USAGE_MATCH(ctypes.Structure):
	_fields_ = (
		("dwType", ctypes.wintypes.DWORD),
		# CERT_ENHKEY_USAGE struct
		("cUsageIdentifier", ctypes.wintypes.DWORD),
		("rgpszUsageIdentifier", ctypes.c_void_p), # LPSTR *
	)

class CERT_CHAIN_PARA(ctypes.Structure):
	_fields_ = (
		("cbSize", ctypes.wintypes.DWORD),
		("RequestedUsage", CERT_USAGE_MATCH),
		("RequestedIssuancePolicy", CERT_USAGE_MATCH),
		("dwUrlRetrievalTimeout", ctypes.wintypes.DWORD),
		("fCheckRevocationFreshnessTime", ctypes.wintypes.BOOL),
		("dwRevocationFreshnessTime", ctypes.wintypes.DWORD),
		("pftCacheResync", ctypes.c_void_p), # LPFILETIME
		("pStrongSignPara", ctypes.c_void_p), # PCCERT_STRONG_SIGN_PARA
		("dwStrongSignFlags", ctypes.wintypes.DWORD),
	)

def _updateWindowsRootCertificates():
	import urllib
	crypt = ctypes.windll.crypt32
	# Get the server certificate.
	sslCont = ssl._create_unverified_context()
	u = urllib.urlopen("https://vocalizer-nvda.com/", context=sslCont)
	cert = u.fp._sock.getpeercert(True)
	u.close()
	# Convert to a form usable by Windows.
	certCont = crypt.CertCreateCertificateContext(
		0x00000001, # X509_ASN_ENCODING
		cert,
		len(cert))
	# Ask Windows to build a certificate chain, thus triggering a root certificate update.
	chainCont = ctypes.c_void_p()
	crypt.CertGetCertificateChain(None, certCont, None, None,
		ctypes.byref(CERT_CHAIN_PARA(cbSize=ctypes.sizeof(CERT_CHAIN_PARA),
			RequestedUsage=CERT_USAGE_MATCH())),
		0, None,
		ctypes.byref(chainCont))
	crypt.CertFreeCertificateChain(chainCont)
	crypt.CertFreeCertificateContext(certCont)
