#vocalizer_globalPlugin/dialogs.py
#A part of the vocalizer driver for NVDA (Non Visual Desktop Access)
#Copyright (C) 2012, 2013 Rui Batista <ruiandrebatista@gmail.com>
#Copyright (C) 2012, 2013 Tiflotecnia, lda. <www.tiflotecnia.com>
#This file is covered by the GNU General Public License.
#See the file GPL.txt for more details.

from collections import defaultdict
import wx
import addonHandler
addonHandler.initTranslation()
import config
import gui
import languageHandler
from logHandler import log
from synthDrivers.vocalizer_expressive import _config, storage
from synthDrivers.vocalizer_expressive._voiceManager import VoiceManager
from synthDrivers.vocalizer_expressive import languageDetection
from .utils import VocalizerOpened

class VocalizerLanguageSettingsDialog(gui.SettingsDialog):
	title = _("Vocalizer Automatic Language Switching Settings")
	def __init__(self, parent):
		with VocalizerOpened():
			manager = VoiceManager()
			self._localeToVoices = manager.localeToVoicesMap
			manager.close()
		self._dataToPercist = defaultdict(lambda : {})
		self._locales = sorted([l for l in self._localeToVoices if len(self._localeToVoices[l]) > 0])
		latinSet = set(languageDetection.ALL_LATIN) & set(l for l in self._locales if len(l) == 2)
		self._latinLocales = sorted(list(latinSet))
		super(VocalizerLanguageSettingsDialog, self).__init__(parent)

	def makeSettings(self, sizer):
		helpLabel = wx.StaticText(self, label=_("Select a locale, and then configure the voice to be used:"))
		helpLabel.Wrap(self.GetSize()[0])
		sizer.Add(helpLabel)
		localesSizer = wx.BoxSizer(wx.HORIZONTAL)
		localesLabel = wx.StaticText(self, label=_("Locale Name:"))
		localesSizer.Add(localesLabel)
		localeNames = list(map(self._getLocaleReadableName, self._locales))
		self._localesChoice = wx.Choice(self, choices=localeNames)
		self.Bind(wx.EVT_CHOICE, self.onLocaleChanged, self._localesChoice)
		localesSizer.Add(self._localesChoice)
		voicesSizer = wx.BoxSizer(wx.HORIZONTAL)
		voicesLabel = wx.StaticText(self, label=_("Voice Name:"))
		voicesSizer.Add(voicesLabel)
		self._voicesChoice = wx.Choice(self, choices=[])
		self.Bind(wx.EVT_CHOICE, self.onVoiceChange, self._voicesChoice)
		voicesSizer.Add(self._voicesChoice)
		self._useUnicodeDetectionCheckBox = wx.CheckBox(self,
		# Translators: Wether to use or not unicode characters based language detection.
			label=_("Detect text language based on unicode characters (experimental)"))
		self._useUnicodeDetectionCheckBox.SetValue(_config.vocalizerConfig['autoLanguageSwitching']['useUnicodeLanguageDetection'])
		
		self._ignorePonctuationAndNumbersCheckBox = wx.CheckBox(self,
		# Translators: Either to ignore or not ASCII punctuation and numbers when language detection is active
		label=_("Ignore numbers and common punctuation when detecting text language (experimental)"))
		self._ignorePonctuationAndNumbersCheckBox.SetValue(_config.vocalizerConfig['autoLanguageSwitching']['ignorePonctuationAndNumbersInLanguageDetection'])
		
		latinSizer = wx.BoxSizer(wx.HORIZONTAL)
		latinLabel = wx.StaticText(self,
		# Translators: Option to set what language to assume for latin characters, in language detection
		label=_("Language assumed for latin characters:"))
		latinChoiceLocaleNames = [self._getLocaleReadableName(l) for l in self._latinLocales]
		self._latinChoice = wx.Choice(self, choices=latinChoiceLocaleNames)
		latinLocale = _config.vocalizerConfig['autoLanguageSwitching']['latinCharactersLanguage']
		try:
			self._latinChoice.Select(self._latinLocales.index(latinLocale))
		except ValueError:
			self._latinChoice.Select(0)
		latinSizer.Add(latinLabel)
		latinSizer.Add(self._latinChoice)
		
		sizer.Add(localesSizer)
		sizer.Add(voicesSizer)
		sizer.Add(self._useUnicodeDetectionCheckBox)
		sizer.Add(self._ignorePonctuationAndNumbersCheckBox)
		sizer.Add(latinSizer)

	def postInit(self):
		self._updateVoicesSelection()
		self._localesChoice.SetFocus()

	def _updateVoicesSelection(self):
		localeIndex = self._localesChoice.GetCurrentSelection()
		if localeIndex < 0:
			self._voicesChoice.SetItems([])
		else:
			locale = self._locales[localeIndex]
			voices = sorted(self._localeToVoices[locale])
			self._voicesChoice.SetItems(voices)
			if locale in _config.vocalizerConfig['autoLanguageSwitching']:
				voice = _config.vocalizerConfig['autoLanguageSwitching'][locale]['voice']
				if voice:
					self._voicesChoice.Select(voices.index(voice))

	def onLocaleChanged(self, event):
		self._updateVoicesSelection()

	def onVoiceChange(self, event):
		localeIndex = self._localesChoice.GetCurrentSelection()
		if localeIndex >= 0:
			locale = self._locales[localeIndex]
			self._dataToPercist[locale]['voice'] = self._voicesChoice.GetStringSelection()
		else:
			self._dataToPercist[locale]['voice'] = None

	def onOk(self, event):
		# Update Configuration
		_config.vocalizerConfig['autoLanguageSwitching'].update(self._dataToPercist)
		_config.vocalizerConfig['autoLanguageSwitching']['useUnicodeLanguageDetection'] = self._useUnicodeDetectionCheckBox.GetValue()
		_config.vocalizerConfig['autoLanguageSwitching']['ignorePonctuationAndNumbersInLanguageDetection'] = self._ignorePonctuationAndNumbersCheckBox.GetValue()
		_config.vocalizerConfig['autoLanguageSwitching']['latinCharactersLanguage'] = self._latinLocales[self._latinChoice.GetCurrentSelection()]
		_config.save()
		return super(VocalizerLanguageSettingsDialog, self).onOk(event)

	def _getLocaleReadableName(self, locale):
		description = languageHandler.getLanguageDescription(locale)
		return "%s - %s" % (description, locale) if description else locale

class EnterCredentialsDialog(gui.SettingsDialog):
	# Translators: Title of the dialog that prompts for vocalizer credentials.
	title = _("Enter your Vocalizer Credentials")
	def __init__(self, parent,email="", password="",  callbackNext=None):
		self._email = email
		self._password = password
		self._callbackNext = callbackNext
		super(EnterCredentialsDialog, self).__init__(parent)

	def makeSettings(self, sizer):
		emailSizer = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: This is the email Address people use to identify on Vocalizer licenses.
		emailLabel = wx.StaticText(self, label=_("Email Address:"))
		self._emailEdit = wx.TextCtrl(self, wx.ID_ANY)
		self._emailEdit.SetValue(self._email)
		emailSizer.Add(emailLabel)
		emailSizer.Add(self._emailEdit)
		sizer.Add(emailSizer)

		passwordSizer = wx.BoxSizer(wx.HORIZONTAL)
		# Translators: This is the password people use to identify on Vocalizer licenses.
		passwordLabel = wx.StaticText(self, label=_("Password:"))
		self._passwordEdit = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_PASSWORD)
		self._passwordEdit.SetValue(self._password)
		passwordSizer.Add(passwordLabel)
		passwordSizer.Add(self._passwordEdit)
		sizer.Add(passwordSizer)
		if config.isInstalledCopy():
			# Translators: check box to prompt the user wether to store or not the password on this computer, when NVDA is installed.
			storeCheckBoxLabel = _("Store password on this computer (your password will be encrypted)")
		else:
			# Translators: Store password on Portable configuration of NVDA
			storeCheckBoxLabel = _("Store Credentials in portable NVDA configuration (your password will be stored in clear text)")
		self._storePasswordCheckBox = wx.CheckBox(self, label=storeCheckBoxLabel)
		self._storePasswordCheckBox.SetValue(bool(self._email) or config.isInstalledCopy())
		sizer.Add(self._storePasswordCheckBox)

	def postInit(self):
		self._emailEdit.SetFocus()

	def onOk(self, event):
		email = self._emailEdit.GetValue()
		password = self._passwordEdit.GetValue()
		if not email or not password:
			gui.messageBox(_("You must enter both email and password values."),
				caption=_("Error"), style=wx.ICON_ERROR)
			return
		try:
			self.validateCredentials(email, password)
		except:
			log.error("Error validating vocalizer credentials.", exc_info=True)
			return
		
		if self._storePasswordCheckBox.GetValue():
			storage.saveCredentials(email, password)
		else:
			storage.saveCredentials(email, password=None)
		if self._callbackNext:
			wx.CallAfter(self._callbackNext, email, password)
		return super(EnterCredentialsDialog, self).onOk(event)

	def validateCredentials(self, email, password):
		from .vocalizer_validation_client import VocalizerValidationClient
		import urllib
		def showError(error):
			message = _("Error verifying credentials: {error}").format(error=error)
			gui.messageBox(message, _("Error"), style=wx.ICON_ERROR)
		client = VocalizerValidationClient(email, password)
		progressDialog = gui.IndeterminateProgressDialog(self, _("Verifying credentials."), _("Please wait while your credentials are being verified..."))
		try:
			gui.ExecAndPump(lambda : client.getLicenseInfo())
		except urllib.error.HTTPError as e:
			error = _("Unknown HTTP error: {code}.".format(code=e.code))
			code = int(e.code)
			if code == 401:
				error = _("Wrong email or password.")
			elif code == 404:
				error = _("No account was found with given email address.")
			elif code == 403:
				error = _("Access is not allowed.")
			showError(error)
			raise
		except urllib.error.URLError:
			showError(_("Can not connect to Vocalizer for NVDA server. Please check if your internet connection is working."))
			raise
		finally:
			progressDialog.done()
		gui.messageBox(_("Your credentials were verified successfully. Press OK to continue."),
		caption=_("Success"), style=wx.ICON_WARNING)
