const puppeteer = require("puppeteer");

const LOGIN_URL = "https://leetcode.com/accounts/login/";
const GRAPHQL_URL = "https://leetcode.com/graphql";
const USER_STATUS_QUERY = "query { userStatus { isSignedIn username } }";

function fail(message) {
  console.error("POC_RESULT=FAILED");
  console.error(`REASON=${message}`);
  process.exitCode = 1;
}

(async () => {
  const email = process.env.LEETCODE_EMAIL;
  const password = process.env.LEETCODE_PASSWORD;

  if (!email || !password) {
    fail("Missing LEETCODE_EMAIL or LEETCODE_PASSWORD repository secret.");
    return;
  }

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    });

    const page = await browser.newPage();
    page.setDefaultTimeout(15000);
    await page.goto(LOGIN_URL, { waitUntil: "domcontentloaded", timeout: 45000 });

    const loginSelector = await firstVisible(page, [
      "#id_login",
      'input[name="login"]',
      'input[type="email"]',
    ]);
    const passwordSelector = await firstVisible(page, [
      "#id_password",
      'input[name="password"]',
      'input[type="password"]',
    ]);

    if (!loginSelector || !passwordSelector) {
      const pageState = await page.evaluate(() => ({
        url: location.href,
        title: document.title,
        text: (document.body?.innerText || "").slice(0, 1200),
      }));
      if (/captcha|cloudflare|verify you are human|security challenge|turnstile/i.test(
        pageState.url + " " + pageState.title + " " + pageState.text
      )) {
        fail(`LeetCode presented a CAPTCHA or security challenge [title: "${pageState.title}", url: ${pageState.url}]. Manual verification is required.`);
      } else {
        fail(`Login form fields were not found [title: "${pageState.title}", url: ${pageState.url}]; LeetCode may have changed its login page or blocked the request.`);
      }
      return;
    }

    await page.click(loginSelector);
    await page.type(loginSelector, email, { delay: 25 });
    await page.click(passwordSelector);
    await page.type(passwordSelector, password, { delay: 25 });

    const submitSelector = await firstVisible(page, [
      "#signin_btn",
      'button#signin_btn',
      'button[type="submit"]',
      'input[type="submit"]',
      'button[id*="sign"]',
    ]);
    if (!submitSelector) {
      fail("Login submit control was not found.");
      return;
    }

    await Promise.all([
      page.click(submitSelector),
      page.waitForNetworkIdle({ idleTime: 1000, timeout: 20000 }).catch(() => null),
    ]);

    // Do not solve or bypass CAPTCHA, MFA, or security challenges.
    const challenge = await page.evaluate(() => {
      const text = (document.body?.innerText || "").slice(0, 3000);
      return /captcha|cloudflare|verify you are human|security challenge|turnstile|two-factor|verification code/i.test(
        location.href + " " + document.title + " " + text
      );
    });
    if (challenge) {
      fail("A CAPTCHA, MFA, or security verification step is required; no bypass was attempted.");
      return;
    }

    const status = await page.evaluate(async (query, endpoint) => {
      const csrf = document.cookie.split("; ").find((part) => part.startsWith("csrftoken="));
      const csrfValue = csrf ? decodeURIComponent(csrf.split("=").slice(1).join("=")) : "";
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          ...(csrfValue ? { "x-csrftoken": csrfValue } : {}),
        },
        body: JSON.stringify({ query }),
      });
      if (!response.ok) return { httpStatus: response.status };
      const payload = await response.json();
      return {
        isSignedIn: payload?.data?.userStatus?.isSignedIn === true,
        usernamePresent: Boolean(payload?.data?.userStatus?.username),
        graphqlErrors: Array.isArray(payload?.errors) && payload.errors.length > 0,
      };
    }, USER_STATUS_QUERY, GRAPHQL_URL);

    if (!status.isSignedIn) {
      fail(status.httpStatus
        ? `Authenticated status check returned HTTP ${status.httpStatus}.`
        : "LeetCode did not confirm an authenticated user session after login.");
      return;
    }

    const cookies = await page.browserContext().cookies("https://leetcode.com");
    const hasSession = cookies.some((cookie) => cookie.name === "LEETCODE_SESSION" && cookie.value);
    const hasCsrf = cookies.some((cookie) => cookie.name === "csrftoken" && cookie.value);

    if (!hasSession || !hasCsrf) {
      fail(`Authenticated status succeeded, but expected cookies were not both present (session=${hasSession}, csrf=${hasCsrf}).`);
      return;
    }

    // Deliberately never print, upload, or persist cookie values in this proof-of-concept.
    console.log("POC_RESULT=SUCCESS");
    console.log("AUTHENTICATED=true");
    console.log("LEETCODE_SESSION_COOKIE_PRESENT=true");
    console.log("CSRFTOKEN_COOKIE_PRESENT=true");
    console.log("COOKIE_VALUES_EXPOSED=false");
  } catch (error) {
    // Error messages can contain URLs or implementation details, but never log page data or credentials.
    fail(`Browser/login verification error: ${String(error.message || error).slice(0, 240)}`);
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
})();

async function firstVisible(page, selectors, timeout = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    for (const selector of selectors) {
      const element = await page.$(selector);
      if (element && (await element.isVisible().catch(() => false))) {
        return selector;
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}
