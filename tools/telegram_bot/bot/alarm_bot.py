import json
import os
import sys
import time

from datetime import datetime
from random import randrange
from typing import Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler, MessageHandler, Filters

sys.path.append(os.path.abspath('../../..'))
from tools.telegram_bot.lib.constants import KEY
from tools.telegram_bot.lib.helpers import custom_dump, custom_load
from tools.telegram_bot.lib.receiver import Receiver


STATE_FILENAME = 'state.json'

CHECK_EVERY_SECONDS = 1

LEVEL = [KEY.PRODUCTION]

class AlarmBot:
    def __init__(self, config: dict, token: str):
        self._config = config
        self._state = self._load_state()
        self._status = dict()

        self._updater = Updater(token=token, user_sig_handler=self.shutdown)

        self._dispatcher = self._updater.dispatcher

        self._bot = Bot(token=token)

        self._bot.send_message(chat_id=config[KEY.DEV_ID], text='⚠️ Bot is active')

        if KEY.UPDATE in self._state:
            offline_time = time.time_ns() - self._state[KEY.UPDATE]

            if offline_time > config[KEY.TIMEOUT] * KEY.ONE_SECOND:
                self.broadcast(f'✅ Bot is ACTIVE now. Offline time was {offline_time // KEY.ONE_SECOND}s '
                               f'which is more than current Timeout ({config[KEY.TIMEOUT]}s). \n\n'
                               f'Watch item list is not relevant. It will be cleared and you will '
                               f'receive "NEW" messages')
                self._state[KEY.ITEM] = dict()
            else:
                self.broadcast(f'✅ Bot is ACTIVE now. Offline time was {offline_time // KEY.ONE_SECOND}s. '
                               f'Bot will try to safe recover monitor procedure')
        else:
            self.broadcast(f'✅ Bot is ACTIVE now.')

        self._receiver = Receiver(config, self._on_topic_message)

        self._map: Dict[str, int] = dict()


        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(self._check_items, 'interval', seconds=CHECK_EVERY_SECONDS)
        self._scheduler.start()


    ######################################################################
    # PUBLIC METHODS
    ######################################################################

    def stdout(self, message, level=KEY.PRODUCTION):
        if level in LEVEL:
            payload = {
                KEY.UTC: datetime.utcnow().__str__(),
                KEY.MESSAGE: message
            }

            sys.stdout.write(json.dumps(payload) + '\n')
            sys.stdout.flush()

    def broadcast(self, message: str):
        for id in self._state[KEY.ACTIVE]:
            try:
                self._bot.send_message(chat_id=id, text=message)
            except:
                pass

    def shutdown(self, *args):
        self._bot.send_message(chat_id=self._config[KEY.DEV_ID], text='⚠️ Bot is DOWN')
        self.broadcast(f'⚫️ Bot is DOWN')
        self._save_state()
        self._scheduler.shutdown()
        self._receiver.shutdown()

    def run(self):
        self._register_handlers()
        self._updater.start_polling()
        self._updater.idle()

    ######################################################################
    # PUBLIC METHODS
    ######################################################################


    def _check_items(self):
        """
        This method check every "CHECK_EVERY_SECONDS" time from last
        update for each item

        It alert with broadcasting message if no updates more than TIMEOUT (from config)

        :return:
        """
        self.stdout(f'Regular items checkout', level=KEY.DEBUG)

        for item in list(self._state[KEY.ITEM].keys()):
            timestamp = self._state[KEY.ITEM][item]
            if timestamp < 0 :
                self.stdout(f'{item}: Candidate', level=KEY.DEBUG)
            else:
                delta = time.time_ns() - timestamp
                if delta < self._config[KEY.TIMEOUT] * KEY.ONE_SECOND:
                    self.stdout(f'{item}: {delta/ KEY.ONE_SECOND}', level=KEY.DEBUG)
                else:
                    self.stdout(f'{item}: Out of time')
                    self.broadcast(f'🔴 {item}: Out of time')
                    del self._state[KEY.ITEM][item]

    def _safe_get_json_payload(self, payload: dict, key: str) -> Optional[dict]:
        data = payload.get(key, '{}')
        try:
            return_me = json.loads(data)
        except:
            return_me = {}

        return return_me

    def _create_message_from_json(self, payload: Optional[dict]) -> str:
        if payload is None:
            message = 'No data'
        else:
            message = json.dumps(payload, default=custom_dump, indent=2)

        return message

    def _on_topic_message(self, message: str):
        """
        This method handle message from Hazelcast or other messaging system
        and update time in items list

        :param message:
        :return:
        """
        try:
            payload = json.loads(message, object_hook=custom_load)
        except:
            payload = None

        if payload is None:
            return

        item = payload[KEY.PAYLOAD][KEY.ID]
        json_data = self._safe_get_json_payload(payload[KEY.PAYLOAD], KEY.JSON)
        alert = self._safe_get_json_payload(payload[KEY.PAYLOAD], KEY.ALERT)

        self.stdout(f'Message {payload[KEY.PAYLOAD]}', level=KEY.DEBUG)

        if json_data != {}:
            self._status[item] = {**json_data, KEY.TIMESTAMP: datetime.utcnow()}

        if alert != {}:
            message = self._create_message_from_json(alert)
            self.broadcast(f'🅰️\n{message}')

        if item in self._state[KEY.ITEM]:
            timestamp = self._state[KEY.ITEM][item]

            if timestamp > 0:
                self._state[KEY.ITEM][item] = time.time_ns()
            else:
                delta = time.time_ns() - abs(timestamp)

                if delta < self._config[KEY.TIMEOUT] * KEY.ONE_SECOND:
                    self.stdout(f'New item: {item}')
                    self.broadcast(f'🔵 New item: {item}')
                    self._state[KEY.ITEM][item] = time.time_ns()
                else:
                    self._state[KEY.ITEM][item] = -time.time_ns()
        else:
            self._state[KEY.ITEM][item] = -time.time_ns()

    def _on_new_user(self, update: Update):
        """
        For new user request we just notificate to DEV user. DEV user should add
        chat_id manually.

        TODO: Make approvements using verification codes
        :param update:
        :return:
        """

        verification_code = randrange(100_000, 999_999)
        update.message.reply_text('✳️ You are new user. Verification code has been sent to DEV. Type it to join')
        self._bot.send_message(chat_id=self._config[KEY.DEV_ID],
                               text=f'⚠️ NEW USER: {update.effective_chat.id} {update.effective_chat.full_name}. '
                                    f'Code {verification_code}')
        self.stdout(f'New user request: {update.effective_chat.id} {update.effective_chat.full_name} Code {verification_code}')
        self._state[KEY.PENDING][update.effective_chat.id.__str__()] = verification_code
        self._save_state()

    def _on_valid_user(self, update: Update):
        """
        Is user is valid -- let him choose STOP or CONTINUE alerts subscription
        :param update:
        :return:
        """
        keyboard = [
            [
                InlineKeyboardButton("Subscribe", callback_data=KEY.SUBSCRIBE),
                InlineKeyboardButton("Unsubsribe", callback_data=KEY.UNSUBSCRIBE),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text('You are valid user. Please choose the action:', reply_markup=reply_markup)


    def _on_start(self, update: Update, context: CallbackContext):
        if update.effective_chat.id in self._state[KEY.VALID]:
            self._on_valid_user(update)
        else:
            self._on_new_user(update)

    def _on_status(self, update: Update, context: CallbackContext):
        keyboard = []

        for item in self._state[KEY.ITEM].keys():
            keyboard.append([InlineKeyboardButton(item, callback_data=item)])

        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text('LIST', reply_markup=reply_markup)

    def _on_code(self, update: Update, context: CallbackContext):
        id = update.effective_chat.id.__str__()

        if id in self._state[KEY.PENDING]:
            try:
                code = int(update.message.text)
            except:
                code = -1

            if code == self._state[KEY.PENDING][id]:
                self._state[KEY.VALID].append(int(id))
                del self._state[KEY.PENDING][id]
                self._save_state()
                self._on_valid_user(update)
            else:
                update.message.reply_text(f'❌ Wrong code!')


    def _button(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        query.answer()

        if query.data in self._state[KEY.ITEM].keys():
            message = self._create_message_from_json(self._status.get(query.data, None))
            query.edit_message_text(text=f"{query.data}\n\n{message}")

        elif query.data == KEY.SUBSCRIBE:
            if update.effective_chat.id not in self._state[KEY.ACTIVE]:
                self._state[KEY.ACTIVE].append(update.effective_chat.id)

            query.edit_message_text(text=f"💚 Notifications are ON now")
            self.stdout(f'Set notifications ON for {update.effective_chat.full_name} ({update.effective_chat.id})')
        else:
            if update.effective_chat.id in self._state[KEY.ACTIVE]:
                self._state[KEY.ACTIVE].remove(update.effective_chat.id)

            query.edit_message_text(text=f"🖤 Notifications are OFF now")
            self.stdout(f'Set notifications OFF for {update.effective_chat.full_name} ({update.effective_chat.id})')

        self._save_state()

    def _register_handlers(self):
        self._dispatcher.add_handler(
            CommandHandler(
                command='start',
                callback=self._on_start,
            )
        )

        self._dispatcher.add_handler(
            CommandHandler(
                command='status',
                callback=self._on_status,
            )
        )

        self._dispatcher.add_handler(
            MessageHandler(
                filters=Filters.text,
                callback=self._on_code
            )
        )

        self._dispatcher.add_handler(CallbackQueryHandler(self._button))


    def _add_valid_user(self, chat_id):
        if chat_id not in self._state[KEY.VALID]:
            self._state[KEY.VALID].append(chat_id)
        self._save_state()

    def _save_state(self):
        self._state[KEY.UPDATE] = time.time_ns()
        with open(STATE_FILENAME, 'w') as fp:
            json.dump(self._state, fp, default=custom_dump, indent=2)

    def _load_state(self) -> dict:
        state = dict()

        # try to load from file
        if os.path.isfile(STATE_FILENAME):
            with open(STATE_FILENAME, 'r') as fp:
                state = json.load(fp, object_hook=custom_load)

        # Fill default lists
        for key in [KEY.VALID, KEY.ACTIVE]:
            if key not in state:
                state[key] = []

        # Fill default dicts
        for key in [KEY.ITEM, KEY.PENDING]:
            if key not in state:
                state[key] = dict()

        return state

