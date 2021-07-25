# -*- coding: utf-8 -*-
#vocalizer_globalPlugin/__init__.py
#A part of the vocalizer driver for NVDA (Non Visual Desktop Access)
#Copyright (C) 2012, 2013 Rui Batista <ruiandrebatista@gmail.com>
#Copyright (C) 2012, 2013 Tiflotecnia, lda. <www.tiflotecnia.com>
#This file is covered by the GNU General Public License.
#See the file GPL.txt for more details.

import datetime
import gettext
import os.path
import shutil
import subprocess
import threading
import time
import webbrowser

import configobj
import wx

import addonHandler
addonHandler.initTranslation()
import core
import globalPluginHandler
import globalVars
import gui
import languageHandler
from logHandler import log
import speech

from .dialogs import *
from .utils import *

from .vocalizer_validation_client import *
import urllib.error
from synthDrivers.vocalizer_expressive import _veTypes


aboutMessage =_("""
URL: {url}

This product is composed of two independent components:
- Nuance Vocalizer Expressive speech synthesizer.
- NVDA speech driver and interface for Nuance Vocalizer.
Licenses and conditions for these components are as follows:

Nuance Vocalizer Expressive speech synthesizer:

Copyright (C) 2013 Nuance Communications, Inc. All rights reserved.

Synthesizer Version: {synthVersion}
This copy of the Nuance Vocalizer synthesizer is licensed to be used exclusively with the NVDA screen reader (Non Visual Desktop Access).

License management components are property of Tiflotecnia, LDA.
Copyright (C) 2012, 2019 Tiflotecnia, LDA. All rights reserved.

---

NVDA speech driver and interface for Nuance Vocalizer Expressive:

Copyright (C) 2012, 2019 Tiflotecnia, LDA.
Copyright (C) 2012, 2019 Rui Batista.
Copyright (C) 2019 Babbage B.V.

Version: {driverVersion}

NVDA speech driver and interface for Nuance Vocalizer is covered by the GNU General Public License (Version 2). You are free to share or change this software in any way you like as long as it is accompanied by the license and you make all source code available to anyone who wants it. This applies to both original and modified copies of this software, plus any derivative works.
For further details, you can view the license from the NVDA Help menu.
It can also be viewed online at: http://www.gnu.org/licenses/old-licenses/gpl-2.0.html

This component was developed by Tiflotecnia, LDA and Rui Batista, with contributions from many others. Special thanks goes to:
{contributors}
""")

contributors = "NV Access ltd, ângelo Abrantes, Diogo Costa, Mesar Hameed, Sérgio Neves, NVDA translation team."


URL = "https://vocalizer-nvda.com"
VOICE_DOWNLOADS_URL_TEMPLATE = "https://vocalizer-nvda.com/downloads?lang={lang}"

def getLicenseInfo():
	from synthDrivers.vocalizer_expressive import _vocalizer
	return _vocalizer.getLicenseInfo()

_validationClient = None

def _getValidationClient(activationCode=None):
	global _validationClient
	if _validationClient is None:
		if activationCode is not None:
			_validationClient = VocalizerValidationClient(activationCode, None, True)
		else:
			email, password = storage.getCredentials()
			if not email or not password:
				return None
			_validationClient = VocalizerValidationClient(email, password)
	return _validationClient

RENEW_INTERVAL = 1800


class LicenseRenewer(object):
	def __init__(self, startNow=False, activationCode=None):
		self._timer = wx.PyTimer(self._renew)
		self._thread = None
		self._activationCode = activationCode
		data = storage.getLicenseData()
		if data is None:
			log.error("No license available.")
			return
		if 'lastRenewCheck' in data and not startNow:
			secs = max(0, data['lastRenewCheck'] + RENEW_INTERVAL - time.time())
		else:
			secs = 0
		log.debug("License renewal starting in %d", secs)
		self._timer.Start(secs * 1000)

	def _renew(self):
		with VocalizerOpened():
			licenseInfo = getLicenseInfo()
			renewInfo = licenseInfo.info.licenseInfo.renewInfo
			if not renewInfo:
				# Save last renew time.
				data = storage.getLicenseData()
				data['lastRenewCheck'] = time.time()
				storage.saveLicenseData(data)
				log.debug("Renewal data not available, checking later.")
				self._timer.Start(RENEW_INTERVAL * 1000)
			else:
				if _getValidationClient(self._activationCode) is None:
					# Credentials not set,
					wx.CallAfter(self._requestForCredentials)
					return
				self._timer.Stop()
				token = renewInfo.contents.token
				number = licenseInfo.info.licenseInfo.number
				self._thread = threading.Thread(target=self._doRenew, args=[number, token])
				self._thread.setDaemon(True)
				self._thread.start()

	def _doRenew(self, number, token):
		client = _getValidationClient(self._activationCode)
		try:
			log.debug("Renewing vocalizer license data.")
			newData = client.renew(number, token)
			newData['lastRenewCheck'] = time.time()
			storage.saveLicenseData(newData)
			log.debug("Vocalizer license data was renewed.")
			self._timer.Stop()
			#self._timer.Start(RENEW_INTERVAL * 1000)
		except IOError as e:
			log.error("Error renewing license.", exc_info=True)
			self._reportError(e)

	def _reportError(self, error):
		if isinstance(error, urllib.error.HTTPError) and error.getcode() in (401, 403, 404):
			wx.CallAfter(gui.messageBox,
			# Translators :message that is presented to the user on renewal slcense error.
			_("Your license can not be verified. Please check the following:\n"
			"1. Your credentials (email and password) are correct (you can change them under the vocalizer expressive menu)\n"
			"2. You are not using someone else's activation or you are not using the same activation in different computers at the same time. This is not legal, and is against license terms.\n"
			"3. You are having internet problems.\n\n"
			"For further clarification, please contact tiflotecnia, Lda, or your local dealer."),
			# Translators: Vocalizer for NVDA error dialog title.
			caption=_("Vocalizer for NvDA Error"), style=wx.ICON_ERROR)

	def _requestForCredentials(self):
		gui.messageBox(
			# Translators: Message telling the user his credentials are not set.
			_("Your Vocalizer for NVDA credentials are not set for this computer.\n"
			"You will need to set them to use vocalizer for NVDA for long time periods, so your license can be properly verified."),
			_("Vocalizer for NVDA warning"),
			style=wx.ICON_WARNING)

	def terminate(self):
		self._timer.Stop()
		if self._thread:
			self._thread.join()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super(GlobalPlugin, self).__init__()
		self._running = False
		self._renewer = None
		if globalVars.appArgs.secure:
			return
		# See if we have at least one voice installed
		if not any(addon.name.startswith("vocalizer-expressive-voice-") for addon in addonHandler.getRunningAddons()):
			wx.CallLater(2000, self.onNoVoicesInstalled)
			return
		data = storage.getLicenseData()
		self._doLicenseWork = data is not None and (data['installed'] and config.isInstalledCopy() or \
			(not data['installed'] and not config.isInstalledCopy()))
		with VocalizerOpened():
			self.createMenu()
			if self._doLicenseWork:
				info = getLicenseInfo()
				activationCode = None
				if int(info.info.licenseInfo.userId) == -1:
					# Using unregistered Activation code.
					activationCode = info.info.licenseInfo.userName
				startNow = info.type == _veTypes.VALIDATION_INVALID
				self._renewer = LicenseRenewer(startNow=startNow, activationCode=activationCode)
			self.showInformations()
		self._running = True

	def createMenu(self):
		self.submenu_vocalizer = wx.Menu()
		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("Automatic &Language Switching Settings"), _("Configure which voice is to be used for each language."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU , lambda e : gui.mainFrame._popupSettingsDialog(VocalizerLanguageSettingsDialog), item)
		licenseInfo = getLicenseInfo()
		data = storage.getLicenseData()
		if licenseInfo.type != _veTypes.VALIDATION_LICENSED and not data:
			# Translators: Menu Item to enter Vocalizer license credentials and activate a license.
			item = self.submenu_vocalizer.Append(wx.ID_ANY, _("Activate License"),
			# Translators: Hint for the activation license menu
			_("Enter license credentials and activate for this computer."))
			gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU , self.onVocalizerLicenseMenu, item)
		else:
			licenseMenu = wx.Menu()
			# Translators: Menu item to open a dialog with vocalizer license information
			item = licenseMenu.Append(wx.ID_ANY, _("View License Information"),
			# Translators: Hint for the license information menu item.
			_("Check information about your Vocalizer license."))
			gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU , self.onVocalizerLicenseInfoMenu, item)
			if self._doLicenseWork and licenseInfo.info.licenseInfo.userId is not None and int(licenseInfo.info.licenseInfo.userId) != -1:
				item = licenseMenu.Append(wx.ID_ANY,
				# Translators: Check activation count menu option
				_("Check activation count"),
				# Translators: Check activation count menu option tooltip.
				_("Allows you to check your Vocalizer for NVDA activation count."))
				gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onCheckActivationCount, item)
				item = licenseMenu.Append(wx.ID_ANY,
				# Translators: Delete Activation menu option
				_("Delete Activation"),
				# Translators: Tooltip for deleting activation.
				_("Deletes the vocalizer for NVDA activation. Can not be reverted."))
				gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onRemoveLicenseMenu, item)
			else:
				item = licenseMenu.Append(wx.ID_ANY,
				# Translators: Register license menu option
				_("Register this license."),
				# Translators: Tooltip for register license menu item.
				_("Register this license with a vocalizer for NVDA account."))
				gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onRegisterLicenseMenu, item)
			self.submenu_vocalizer.AppendSubMenu(
				licenseMenu,
				# Translators: Submenu with license related options
				_("License Options")
			)

		item = self.submenu_vocalizer.Append(wx.ID_ANY,
		# Translators: Change credentials menu item
		_("Change account credentials"),
		# Translators: Tooltip for change credentials option.
		_("Allows setting of email and password that are used to access the Vocalizer licenses service."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onChangeCredentials, item)

		if not config.isInstalledCopy() and licenseInfo.type == _veTypes.VALIDATION_LICENSED and 'installed' in data and data['installed']:
			item = self.submenu_vocalizer.Append(wx.ID_ANY,
			# Translators: Menu item to Activate license on running portable copy.
			_("Activate on portable copy"),
			# Translators: Help for activate on portable copy menu item.
			_("Activates a vocalizer for NVDA license on running portable copy, if an activation is already present on the computer"))
			gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onActivatePortableCopy, item)
		
		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("Download More Voices"), _("Open the vocalizer voices download page."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onVoicesDownload, item)
		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("About Nuance Vocalizer for NVDA"))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onAbout, item)
		self.submenu_item = gui.mainFrame.sysTrayIcon.menu.Insert(2, wx.ID_ANY, _("Vocalizer Expressive"), self.submenu_vocalizer)

	def removeMenu(self):
		if self.submenu_item is not None:
			try:
				gui.mainFrame.sysTrayIcon.menu.Remove(self.submenu_item)
			except AttributeError: # We can get this somehow from wx python when NVDA is shuttingdown, just ignore
				pass
			self.submenu_item.Destroy()

	def onVocalizerLicenseMenu(self, event):
		email, password = storage.getCredentials()
		if not email or not password:
			if not email:
				email = ""
			gui.mainFrame._popupSettingsDialog(EnterCredentialsDialog, email=email, password="", callbackNext=self.onActivate)
		else:
			self.onActivate(email, password)

	def onActivatePortableCopy(self, event):
		if gui.messageBox(
		# Translators: Message asking the user if he wants to activate a license on the running portable copy
		_("Are you sure you want to activate your license on the running portable copy?\n"
		"Only do this if you are preparing a portable NVDA on a computer where\n"
		"a Vocalizer for NVDA license is present."),
		caption=_("Are you sure?"), style=wx.ICON_QUESTION|wx.YES_NO) == wx.NO:
			return
		email, password = storage.getCredentials()
		storage.saveCredentials(email, password, forcePortable=False)
		self.onActivate(email, password, forcePortable=True)

	def onActivate(self, email, password, forcePortable=False):
		progressDialog = self._popupProgressDialog()
		client = _getValidationClient()
		try:
			gui.ExecAndPump(self.callAndPass, client.getLicenseInfo, self._processInfoForActivation, forcePortable)
		except urllib.error.HTTPError as e:
			self._reportHttpError(e)
			raise
		finally:
			progressDialog.done()
			del progressDialog

	def _processInfoForActivation(self, info, forcePortable=False):
		client = _getValidationClient()
		if info['remainingLicenses'] <= 0:
			gui.messageBox(
				# Translators: message telling the user he has no activations left.
				_("You have no activations left for your license. Please contact Tiflotecnia, lda, or your local distributor of Vocalizer for NVDA."),
				# Translators: Title for the activation error message box.
				caption=_("Activation Error"), style=wx.ICON_ERROR)
			return
		if gui.messageBox(
			# Translators: Message telling the user its current license count and information, and asking if he wants to activate his license on this NVDA copy
			_("{name}, you currently have {remainingLicenses} activations left.\n"
			"Do you want to activate Nuance Vocalizer for NVDA on this installation?\n"
			"If you do so, your activation count will be decreased by one.").format(**info),
			# Translators: Title for the activation dialog.
			caption=_("Nuance Vocalizer Activation"), style=wx.ICON_QUESTION|wx.YES_NO) == wx.YES:
			progressDialog = self._popupProgressDialog()
			try:
				gui.ExecAndPump(self.callAndPass, client.activateLicense, self._processActivationData, forcePortable)
			except urllib.error.HTTPError as e:
				self._reportHttpError(e)
			finally:
				progressDialog.done()
				del progressDialog

	def _processActivationData(self, data, forcePortable=False):
		client = _getValidationClient()
		storage.saveLicenseData(data, forcePortable=forcePortable)
		gui.messageBox(
			# Translators: Message telling the user activation was sucessful
			_("Your license is now enabled.\n"
			"NVDA will now be restarted.\n"
			"Thank you for using Vocalizer for NVDA."),
			# Translators: Successfull activation dialog title.
			caption=_("Success!"), style=wx.ICON_INFORMATION)
		core.restart()

	def _popupProgressDialog(self):
		return gui.IndeterminateProgressDialog(gui.mainFrame,
		# Translators: Title of the dialog telling the user to wait for communication with vocalizer server.
		_("Talking with Vocalizer for NVDA server."),
		# Translators: Message telling the user to waith for the communication to server to happen.
		_("Please wait while the communication with Vocalizer for NVDA server is performed."))

	def callAndPass(self, func, next, *args):
		ret = func()
		wx.CallAfter(wx.CallLater, 100, next, ret, *args)

	def onVocalizerLicenseInfoMenu(self, event):
		with VocalizerOpened():
			licenseInfo = getLicenseInfo()
			if licenseInfo.type in (_veTypes.VALIDATION_LICENSED, _veTypes.VALIDATION_INVALID):
				userName = licenseInfo.info.licenseInfo.userName
				email = licenseInfo.info.licenseInfo.email
				distributor = licenseInfo.info.licenseInfo.distributor
				number = licenseInfo.info.licenseInfo.number
				# Translators: Information about vocalizer license:
				message = _("User Name:\t{userName}\n"
				"Email:\t{email}\n"
				"Distributor:\t{distributor}\n"
				"Activation Number:\t{number}\n").format(**locals())
				# Translators: License information dialog title.
				title = _("License Information")
				gui.messageBox(message, caption=title, style=wx.ICON_INFORMATION)
			else:
				log.error("Can't get information about license.")

	def _reportHttpError(self, error):
		# Translators: General error information title.
		title = _("error")
		if error.getcode() == 401:
			# Translators: Error message telling the user that credentials are wrong.
			message = _("Yourr email or password is incorrect. Please set your credentials.")
		elif error.getcode() == 404:
			# Translators: Error message telling the user the requested license was not found
			message = _("License not found. Please check you have a vocalizer for NVDA license enabled.")
		else:
			# Translators: general error message
			message  = _("Unknown error occured.\n"
			"Details: {error}").format(error=error)
		gui.messageBox(message, caption=title, style=wx.ICON_ERROR)

	def onRemoveLicenseMenu(self, event=None, retry=False):
		client = _getValidationClient()
		if not retry and client is None:
			if gui.messageBox(
				# Translators: Message telling the user he has to set is credentials to remove the license
				_("You must set your vocalizer expressive account credentials before removing the license.\n"
				"Do you want to set them now?"),
				# Translators: Error
				_("Error"),
				style=wx.YES_NO|wx.ICON_ERROR)== wx.YES:
					wx.CallAfter(self.onChangeCredentials, None, self.onRemoveLicenseMenu, [None, True])
			return
		if gui.messageBox(
		# Translators: Message warning the user that removing an activation can not be reverted.
		_("Are you sure you want to delete this Nuance Vocalizer for NVDA activation?\n"
		"This action can not be reverted.\n"),
		# Translators: title for delete activation dialog
		caption=_("Are you sure?"),
		style=wx.YES_NO|wx.NO_DEFAULT|wx.ICON_EXCLAMATION) == wx.YES:
			progressDialog = self._popupProgressDialog()
			try:
				gui.ExecAndPump(self._removeLicense, client)
			except urllib.error.HTTPError as e:
				self._reportHttpError(e)
				raise
			finally:
				progressDialog.done()
				del progressDialog

	def _removeLicense(self, client):
		with VocalizerOpened():
			licenseInfo = getLicenseInfo()
			number = licenseInfo.info.licenseInfo.number
		client.disable(number)
		log.debug("License disabled.")
		storage.saveLicenseData(None)
		log.debug("License data deleted.")
		info = client.getLicenseInfo()
		wx.CallAfter(wx.CallLater, 100, self._removeLicenseSuccess, info)

	def _removeLicenseSuccess(self, info):
		gui.messageBox(
			# Translators: Message confirming successfull activation removal.
			_("{name}, Your activation was deleted.\n"
			"You have {remainingLicenses} activations left.\n"
				"NVDA will now be restarted.").format(**info),
				# Translators: Title of successful activation removal dialog
				caption=_("Activation Deleted."),
				style=wx.ICON_INFORMATION)
		storage.deleteCredentials()
		core.restart()

	def onChangeCredentials(self, event=None, callback=None, callbackArgs=[]):
		global _validationClient
		email, password = storage.getCredentials()
		if email is None:
			email = ""
		if password is None:
			password = ""
		if callback:
			c = lambda email, password : callback(*callbackArgs)
		else:
			c = None
		_validationClient = None
		gui.mainFrame._popupSettingsDialog(EnterCredentialsDialog, email, password, c)

	def onRegisterLicenseMenu(self, event):
		email, password = storage.getCredentials()
		if email and password:
			self._registerLicense(email, password)
		else:
			if gui.messageBox(
			# Translators: Message telling the user that he must register on the vocalizer web site first
			_("To register your license you must create an account on the vocalizer web site."
			"If you already have an account you may just continue.~\n"
			"Do you want to create an account now?"),
			# Translators: Title of register dialog message
			_("Vocalizer account needed"),
			style=wx.YES_NO|wx.YES_DEFAULT) == wx.ID_YES:
				webbroser.open("https://vocalizer-nvda.com/register")
			if not email:
				email = ""
			gui.mainFrame._popupSettingsDialog(EnterCredentialsDialog, email=email, password="", callbackNext=self._registerLicense)

	def _registerLicense(self, email, password):
		global _validationClient
		_validationClient = None
		code = None
		number = None
		with VocalizerOpened():
			info = getLicenseInfo()
			code = info.info.licenseInfo.userName
			number = info.info.licenseInfo.number
		client = _getValidationClient()
		res = []
		progressDialog = self._popupProgressDialog()
		error = False
		try:
			gui.ExecAndPump(lambda : res.append(client.registerLicenseFromActivationCode(code, number)))
		except:
			error = True
			log.error("Error registering license.", exc_info=True)
		finally:
			progressDialog.done()
			del progressDialog

		if error:
			gui.messageBox(
			# Translators: Error message in registering license.
			_("There was an error registering your license."
			"Please contact your distributor for help. The log file may contain further information."),
			# Translators: Register error message title
			_("Error registering license."),
			style=wx.ICON_ERROR)
			return
		res[0]['installed'] = config.isInstalledCopy()
		storage.saveLicenseData(res[0])
		gui.messageBox(
			# Translators: Message telling the user registration was successful.
			_("Registration was successful. NVDA will now be restarted."),
			# Translators: Title of successful registration message dialog
			_("Registration Successful."))
		core.restart()

	def onCheckActivationCount(self, event):
		email, password = storage.getCredentials()
		if not email or not password:
			gui.messageBox(
			# Translators: Message telling the user he must set his credentials to see his activation count.
			_("You must set your Vocalizer for NVDA credentials before checking your activation count."),
			# Translators: Title of dialog informing the user he must set is credentials.
			caption=_("No credentials set"), style=wx.ICON_ERROR)
			return
		client = VocalizerValidationClient(email, password)
		progressDialog = self._popupProgressDialog()
		try:
			gui.ExecAndPump(self.callAndPass, client.getLicenseInfo, self.processActivationCount)
		except urlib2.HTTPError as e:
			self._reportHttpError(e)
			raise
		finally:
			progressDialog.done()

	def processActivationCount(self, info):
		gui.messageBox(
		# Translators : Message reporting to the user his activation count.
		_("{name}, you have {remainingLicenses} activations left.").format(**info),
		# Translators: Activation count dialog title.
		caption=_("Activation Count"), style=wx.ICON_INFORMATION)

	def onVoicesDownload(self, event):
		self._openVoicesDownload()

	def _openVoicesDownload(self):
		webbrowser.open(VOICE_DOWNLOADS_URL_TEMPLATE.format(
			lang=languageHandler.getLanguage().split("_")[0]
		))

	def onAbout(self, event):
		from synthDrivers import vocalizer_expressive
		from synthDrivers.vocalizer_expressive import _vocalizer
		synthVersion = vocalizer_expressive.synthVersion
		driverVersion = vocalizer_expressive.driverVersion
		msg = aboutMessage.format(url=URL, contributors=contributors, **locals())
		gui.messageBox(msg, _("About Nuance Vocalizer Expressive for NVDA"), wx.OK)

	def showInformations(self):
		from synthDrivers.vocalizer_expressive import _config
		_config.load()
		licenseInfo = getLicenseInfo()
		if licenseInfo.type == _veTypes.VALIDATION_LICENSED:
			return
		elif licenseInfo.type == _veTypes.VALIDATION_DEMO:
			if licenseInfo.info.demoExpiration < time.time():
				log.info("Vocalizer demo expired.")
				lastReportTime = _config.vocalizerConfig['demo_expired_reported_time']
				# If reported less than one hour ago, don't bother the user.
				if (lastReportTime + 3600) > time.time():
					return
				wx.CallLater(2000, gui.messageBox,
				# Translators: Message telling the user that demo license as expired.
				_("The Nuance Vocalizer for NVDA demonstration license has expired.\n"
				"To purchase a  license for Nuance Vocalizer for NVDA, please visit {url}, or contact an authorized distributor.\n"
				"Note that a percentage of the license's price is donated to NV Access, ltd, to help continuing the development of the NVDA screen reader.").format(url=URL),
				_("Vocalizer Demo Expired"))
				_config.vocalizerConfig['demo_expired_reported_time'] = time.time()
				_config.save()
			else: # Demo not expired.
				log.info("Running demo license.")
				d  = datetime.datetime.fromtimestamp(licenseInfo.info.demoExpiration)
				dateStr = d.strftime("%Y-%m-%d")
				lastReportedTime = _config.vocalizerConfig['demo_license_reported_time']
				if (lastReportedTime + 3600 * 24) > time.time():
					log.debug("Not reporting demo message.")
					return
				wx.CallLater(2000, gui.messageBox,
					# Translators: Message telling the user that he is running a demo license.
					_("You are running a demo version of Nuance Vocalizer expressive for NVDA.\n"
					"This demo will expire on {date}. To use the syntheciser after that,\n"
					"You must buy a license. You can do so at any time by visiting {url} or by contacting a local distributor.\n"
					"Thanks for testing Nuance Vocalizer expressive for NVDA.").format(url=URL, date=dateStr),
					# Translators: Title of vocalizer demo version dialog.
					_("Vocalizer Demo Version"))
				_config.vocalizerConfig['demo_license_reported_time'] = time.time()
				_config.save()
		elif licenseInfo.type == _veTypes.VALIDATION_INVALID:
			wx.CallLater(2000, gui.messageBox,
			_("The Vocalizer license you are trying to use is invalid.\n"
			"This might be happening due to one of two reasons:\n"
			"1. The activation file is damaged.\n"
			"2. The license was disabled for security reasons, due to illegal use or its data beeing compromized.\n"
			"If you own a license for Nuance Vocalizer for NVDA, please contact Tiflotecnia, lda. or your local distributor, so the problem can be further investigated.\n"
			"If this Nuance Vocalizer for NVDA license activation doesn't belong to you, please reframe from using this product.\n"
			"Unauthorized use of this product (i.g. without a valid license) is not allowed by most international laws on software rights.\n"
			"Please note that a proportion of the price of Nuance Vocalizer for NVDA is donated for continuing NVDA's development.\n"
			"By sharing license activations you are working against NVDA and good and cheap accessibility for the blind across the world.\n"
			"Further more, Nuance Vocalizer for NVDA is priced at the lowest value possible, to allow as many people as possible to have a comercial quality syntheciser in NVDA.\n"
			"Please think twice about it.\n"
			"You can remove this invalid license using  the Vocalizer Expressive menu options."),
			caption=_("Vocalizer License is Invalid."))


	def onNoVoicesInstalled(self):
		if gui.messageBox(_("You have no Vocalizer voices installed.\n"
		"You need at least one voice installed to use Vocalizer for NVDA.\n"
		"You can download all Vocalizer voices from the product web page.\n"
		"Do you want to open the vocalizer for NVDA voices download page now?"),
		caption=_("No voices installed."), style=wx.YES_NO|wx.ICON_WARNING) == wx.YES:
			self._openVoicesDownload()

	def  terminate(self):
		if not self._running:
			return
		if self._renewer:
			self._renewer.terminate()
		try:
			self.removeMenu()
		except wx.PyDeadObjectError:
			pass
