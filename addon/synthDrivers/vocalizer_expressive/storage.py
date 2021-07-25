#vocalizer/storage.py
#A part of the vocalizer driver for NVDA (Non Visual Desktop Access)
#Copyright (C) 2013 Rui Batista <ruiandrebatista@gmail.com>
#Copyright (C) 2013 Tiflotecnia, lda. <www.tiflotecnia.com>
#This file is covered by the GNU General Public License.
#See the file GPL.txt for more details.


from ctypes import *
from ctypes.wintypes import *
import itertools
import os.path
import pickle
import config
import globalVars
from logHandler import log
import shlobj

# Structures to use with windows data protection API
class DATA_BLOB(Structure):
	_fields_ = (("cbData", DWORD),
		("pbData", POINTER(c_char)))

crypt32 = windll.crypt32

VOCALIZER_CONFIG_FOLDER = u"vocalizer-for-nvda"
VOCALIZER_LICENSE_FILE = "activation.dat"
VOCALIZER_CREDENTIALS_FILE = "credentials.dat"

def _loadLicenseData(path):
	log.debug(u"Loading license data from %s", path)
	with open(path) as f:
		data = pickle.load(f)
		return data

def _saveLicenseData(path, data):
	log.debug(u"Saving license data to %s", path)
	with open(path, "w") as f:
		pickle.dump(f, data)


def _getLocalConfigFolder():
	return os.path.join(shlobj.SHGetFolderPath(0, shlobj.CSIDL_APPDATA), VOCALIZER_CONFIG_FOLDER)


def _getLicenseDirs(forcePortable=False):
	if not config.isInstalledCopy() or forcePortable:
		yield os.path.join(globalVars.appArgs.configPath, VOCALIZER_CONFIG_FOLDER), False
	yield _getLocalConfigFolder(), True


def _getLicenseDir(forcePortable=False):
	return _getLicenseDirs(forcePortable=forcePortable).next()[0]

_licensePath = None
_licenseData = None

def getLicenseData(forcePortable=True):
	global _licenseData, _licensePath
	if _licenseData is None:
		path = None
		installed = False
		for p, i in _getLicenseDirs(forcePortable):
			trial= os.path.join(p, VOCALIZER_LICENSE_FILE)
			if os.path.isfile(trial):
				path = trial
				installed = i
				break
		if path is not None:
			_licenseData = _loadLicenseData(path)
			_licenseData['installed'] = installed
			_licensePath = path
		else:
			_licenseData = None
	return _licenseData

def getCredentials():
	credentialsPath = None
	installed = None
	for tryal, i in _getLicenseDirs():
		tryPath = os.path.join(tryal, VOCALIZER_CREDENTIALS_FILE)
		if os.path.isfile(tryPath):
			credentialsPath = tryPath
			installed = i
	if credentialsPath is None:
		return None, None
	log.debug(u"Loading credentials from %s", credentialsPath)
	with open(credentialsPath) as f:
		credentials = pickle.load(f)
		email = credentials['email']
		password = credentials['password']
		if password is not None and installed:
			password = _decryptUserData(credentials['password'])
	return email, password

def saveCredentials(email, password, forcePortable=False):
	path = os.path.join(_getLicenseDir(forcePortable=forcePortable), VOCALIZER_CREDENTIALS_FILE)
	log.debug(u"Saving credentials in %s", path)
	try:
		os.makedirs(os.path.dirname(path))
	except WindowsError:
		pass
	if password is not None and config.isInstalledCopy() and (not forcePortable):
		data = dict(email=email, password=_encryptUserData(password))
	else:
		data = dict(email=email, password=password)
	with open(path, "w") as f:
		pickle.dump(data, f)

def deleteCredentials():
	path = os.path.join(_getLicenseDir(), VOCALIZER_CREDENTIALS_FILE)
	if os.path.isfile(path):
		os.unlink(path)


def saveLicenseData(data, forcePortable=False):
	global _licensePath, _licenseData
	_licenseData = data
	if not _licensePath or forcePortable:
		path = os.path.join(_getLicenseDir(forcePortable=forcePortable), VOCALIZER_LICENSE_FILE)
		dir = os.path.dirname(path)
		if not os.path.isdir(dir):
			os.makedirs(dir)
		_licensePath = path
	if data is not None: # Store
		with open(_licensePath, "w") as f:
			pickle.dump(_licenseData, f)
	else: # Delete
		os.unlink(_licensePath)
		_licensePath = None

def _encryptUserData(data):
	dataIn = DATA_BLOB()
	dataIn.cbData = len(data)
	dataIn.pbData = create_string_buffer(data, len(data))
	dataOut = DATA_BLOB()
	if not crypt32.CryptProtectData(byref(dataIn), "", None, None, None, 0, byref(dataOut)):
		raise WindowsError("Can't protect data")
	return string_at(dataOut.pbData, dataOut.cbData)

def _decryptUserData(data):
	dataIn = DATA_BLOB()
	dataIn.cbData = len(data)
	dataIn.pbData = create_string_buffer(data, len(data))
	dataOut = DATA_BLOB()
	if not crypt32.CryptUnprotectData(byref(dataIn), None, None, None, None, 0, byref(dataOut)):
		raise WindowsError("Can't unprotect data")
	return string_at(dataOut.pbData, dataOut.cbData)


