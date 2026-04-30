import requests

from src.core.bot import MusicPartnerBot
from src.utils.config import Config
from src.utils.logger import Logger
from src.utils.notification import NotificationService
from src.validators.cookie import CookieValidator


def main():
    logger = None
    notifier = None

    try:
        config = Config()
        logger = Logger()
        notifier = NotificationService(config, logger)

        session = requests.Session()
        session.cookies.set("MUSIC_U", config.get("Cookie_MUSIC_U"))
        session.cookies.set("__csrf", config.get("Cookie___csrf"))

        validator = CookieValidator(session, logger)
        is_valid, message = validator.validate()

        if not is_valid:
            logger.error(message)
            notifier.send_notification(
                "NCM Partner - Cookie Invalid",
                f"Please refresh the cookie.\n\nDetails: {message}",
            )
            return

        bot = MusicPartnerBot(config, logger, session)
        success = bot.run()

        end_message = "Success" if success else "Failed"
        logger.end(end_message, not success)

        if success:
            notifier.send_notification(
                "NCM Partner - Auto Score Success",
                "Auto Score completed successfully. Check the GitHub Actions run for full details.",
            )
        else:
            notifier.send_notification(
                "NCM Partner - Auto Score Failed",
                "Auto Score finished with a failure status. Please check the GitHub Actions logs.",
            )

    except Exception as error:
        error_message = f"Program exception: {error}"

        if logger is not None:
            logger.error(error_message)
            logger.end("Failed", True)

        if notifier is not None:
            try:
                notifier.send_notification(
                    "NCM Partner - Auto Score Exception",
                    error_message,
                )
            except Exception as notify_error:
                if logger is not None:
                    logger.error(f"Failed to send exception notification: {notify_error}")
                else:
                    print(f"Failed to send exception notification: {notify_error}")
        else:
            print(error_message)


if __name__ == "__main__":
    main()
