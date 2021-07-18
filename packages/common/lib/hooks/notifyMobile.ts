import axios from 'axios';

const {HOOK_NOTIFIER_ENDPOINT, HOOK_NOTIFIER_ID, HOOK_NOTIFIER_KEY} =
  process.env;

// build an interface with a business string, object string and body string
export interface MobileNotification {
  business: string;
  object: string;
  body: string;
}

export const notifyMobile = async (notification: MobileNotification) => {
  try {
    await axios.post(
      `${HOOK_NOTIFIER_ENDPOINT}/${HOOK_NOTIFIER_ID}/${HOOK_NOTIFIER_KEY}`,
      null,
      {params: notification}
    );
  } catch (e) {
    console.log(e);
  }
};
