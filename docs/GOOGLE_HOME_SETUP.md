# Connect Track Things to Google Home

Use this checklist to connect Home Assistant to your Google Nest speaker or
display. You do not need to write code. Menu names may differ slightly between
app versions.

Google Cast lets Home Assistant speak through your Nest. Linking Google Home
also lets you start a configured Home Assistant shortcut by saying “Hey Google”.
These shortcuts do not provide a full conversation with Track Things. For
questions and follow-up answers, use [Home Assistant Assist](ASSIST_CONVERSATION.md).

## Before you start

- [ ] Set up your Nest speaker or display in the Google Home phone app.
- [ ] Connect your phone, Nest, and Home Assistant computer to the same home
  network. Avoid a guest network that prevents devices from communicating.
- [ ] Make sure Home Assistant is installed and opens in your browser.
- [ ] Make sure the Track Things integration is installed and up to date.
  If someone manages Home Assistant for you, ask them to install the integration
  and its supplied blueprints. Blueprints are ready-made templates for shortcuts.
- [ ] Connect your Track Things account, choose your workspace, and select your
  trackers. See [account setup](ACCOUNT_SETUP.md).

## 1. Make Home Assistant reachable by your speaker

- [ ] In Home Assistant, open **Settings → System → Network**.
- [ ] Find **Home Assistant URL → Local network**.
- [ ] Check that this is an address other devices in your home can open. An
  address that works only on the Home Assistant computer is not enough.
- [ ] Open that address on your phone while connected to your home Wi-Fi.

If the page does not open on your phone, ask the person who manages your computer
or router to help. Tell them:

> My Nest needs to reach Home Assistant over our home network. Please check the
> local Home Assistant URL, Docker networking if used, and the computer firewall.
> Allow the intended Nest devices to reach Home Assistant without disabling the
> firewall. Please keep the device addresses stable so the setup continues to work.

Do not copy someone else's network address. Your home has its own settings.
You do not need to make Home Assistant publicly accessible to test speaker output.

## 2. Add your Nest to Home Assistant

- [ ] Open **Settings → Devices & services**.
- [ ] Select **Add integration**, search for **Google Cast**, and follow the
  instructions.
- [ ] Check that your Nest appears. Give it a clear name so you can recognize it.
- [ ] If it is not found, ask your helper to add its network address through
  Google Cast's **Known hosts** setting. Automatic discovery can fail when
  Home Assistant runs in Docker.

You can now open the Nest device page and click its name under **Controls**.
This opens its playback and volume panel. The power button alone does not make
it speak.

## 3. Set up a voice and test sound

- [ ] Under **Settings → Devices & services**, check whether a text-to-speech
  provider is already installed. This is the service that turns text into audio.
- [ ] If needed, choose **Add integration** and search for
  **Google Translate text-to-speech**, then follow its setup instructions.
- [ ] Open **Developer tools → Actions**. Despite the name, this screen can be
  used without code: keep it in the visual form mode.
- [ ] Search for and select **Text-to-speech: Speak** (`tts.speak`).
- [ ] Select your text-to-speech provider as the target.
- [ ] Select your Nest in the media-player field.
- [ ] Enter a short message, such as “Hello, this is a speaker test.”
- [ ] Make sure that Nest is unmuted and its volume is comfortable, then choose
  **Perform action**.
- [ ] Confirm that you hear the message on the selected Nest.

A green success mark means Home Assistant sent the action without reporting an
error. Always listen for the message to confirm playback.

### If you cannot hear anything

- Check that you selected the speaker you are listening to.
- Check its mute and volume controls.
- If an error includes an audio link, try opening that link on your phone using
  the same Wi-Fi as the Nest. Playing it on the Home Assistant computer alone
  does not prove that the Nest can reach it.
- If the phone cannot open the audio, ask your helper to check the local URL and
  firewall using the explanation in step 1.
- If the phone plays it but the Nest does not, ask your helper to check the Cast
  connection and Home Assistant logs.

Get this short message working before adding a Track Things shortcut.

## 4. Create a Track Things shortcut

A shortcut is called a **script** in Home Assistant. Start with a read-only test;
for example, the supplied daily-summary template can read today's entries aloud.

- [ ] Open **Settings → Automations & scenes → Blueprints**.
- [ ] For this example, find **Track Things daily summary** and choose
  **Create script**.
- [ ] Select your Track Things account, the voice provider you tested, and your
  Nest as the fixed output speaker.
- [ ] Choose the summary language and a matching language supported by your
  voice provider. For an English test, use English and the code `en`.
- [ ] Save with a name you can easily say, such as **Track Things daily summary**.
- [ ] Open the **Scripts** tab and choose **Run** from the saved script's menu.
- [ ] Confirm that the Nest speaks. For this example, “zero entries” is a valid
  result if the selected workspace has no entries for today.

If no Track Things blueprint appears, ask your helper to install the supplied
blueprint files. If a script fails, open its **Traces** to see which step failed
and share the error with your helper.

The example always speaks through the speaker selected in the script, even if
another Google device starts it. See [the daily-summary guide](GOOGLE_DAILY_SUMMARY.md)
for more detail about this particular example.

## 5. Connect Google Home for voice commands

The simplest setup uses **Home Assistant Cloud by Nabu Casa**. It requires an
account and has a trial followed by a paid subscription. Check the current terms
before signing up. If Google Home is already linked to Home Assistant, skip the
account-linking steps.

- [ ] In Home Assistant, open **Settings → Home Assistant Cloud** and connect
  your Cloud account.
- [ ] Under **Settings → Voice assistants**, enable **Google Assistant**.
- [ ] Open **Expose** and enable Google Assistant for the shortcut you created.
  Exposing a shortcut makes it available to Google Home. Select only shortcuts
  you want people in your Google household to be able to use.
- [ ] On your phone, open Google Home and choose **Add → Works with Google Home**.
  Some versions call this **Set up device → Works with Google**.
- [ ] Search for **Home Assistant Cloud by Nabu Casa** and link your account.
- [ ] Say **“Hey Google, sync my devices.”**
- [ ] Say **“Hey Google, activate”** followed by your saved shortcut's name.
  For the example above: **“Hey Google, activate Track Things daily summary.”**
- [ ] Confirm that you hear the actual result on the configured output speaker,
  rather than only Google's acknowledgement.

If another household member cannot use the shortcut, assign it to an area in
Home Assistant and sync devices again.

You can optionally create a Google Home routine with a phrase you prefer and
have it activate the same shortcut. Get direct activation working first.

A manual connection without Home Assistant Cloud is also possible, but needs
technical setup. Ask your helper to follow the official Google Assistant guide
below. Local speaker playback alone does not require a Cloud subscription.

## Setup complete

- [ ] A short test message is audible on your Nest.
- [ ] A Track Things shortcut works when run inside Home Assistant.
- [ ] The same shortcut works when activated through “Hey Google”.

This setup uses internet services, including Google voice recognition and Google
Translate speech generation; it is not an offline voice assistant.

The connection steps were used in a successful user-assisted test on
2026-09-10 with Home Assistant 2026.9.1 and Track Things v0.20.0. The user confirmed
speech output, a spoken empty-calendar result, and Google voice activation.
This does not establish compatibility with every Nest model or verify entry
creation and full conversations.

## More help

- [Track Things account setup](ACCOUNT_SETUP.md)
- [Example: daily-summary shortcut](GOOGLE_DAILY_SUMMARY.md)
- [Guided conversations through Assist](ASSIST_CONVERSATION.md)
- [Official Google Cast help](https://www.home-assistant.io/integrations/cast/)
- [Official Home Assistant Cloud linking instructions](https://support.nabucasa.com/hc/en-us/articles/25619376817053-Google-Assistant)
- [Manual Google Assistant setup for your technical helper](https://www.home-assistant.io/integrations/google_assistant/)
