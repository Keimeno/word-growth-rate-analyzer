import axios from 'axios';

const {HOOK_NOTIFIER_ENDPOINT, HOOK_NOTIFIER_ID, HOOK_NOTIFIER_KEY} =
  process.env;

// build an interface with a business string, object string and body string
export interface MobileNotification {
  /**
   * The name of the application
   */
  business: string;

  /**
   * The scope of the notification
   */
  object: string;

  /**
   * The 'body' functions here more as a header than a body.
   */
  body: string;

  /**
   * The 'content' is the 'true' body of the notification.
   */
  content?: string;
}

export const notifyMobile = async (notification: MobileNotification) => {
  try {
    await axios.post(
      `${HOOK_NOTIFIER_ENDPOINT}/${HOOK_NOTIFIER_ID}/${HOOK_NOTIFIER_KEY}`,
      notification.content,
      {params: notification}
    );
  } catch (e) {
    console.log(e);
  }
};
