import { expect, test, type Page } from '@playwright/test';

// The analyst chat panel against a mocked /api/agent/chat stream (fixtures mode + the 'uhd.e2e.chat' hook).
const ready = async (page: Page) => {
  await expect(page.getByTestId('answer')).toBeVisible({ timeout: 30_000 });
  await page.locator('.map[data-ready]').waitFor();
};

const block = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('uhd.e2e.chat', '1'));
});

test('streams steps, repairs once, renders a validated answer with a map link', async ({ page }) => {
  const sent: { body: unknown; team: string | undefined }[] = [];
  await page.route('**/api/agent/chat', async (route) => {
    sent.push({ body: route.request().postDataJSON(), team: route.request().headers()['x-uhd-team-token'] });
    await route.fulfill({
      status: 200, headers: { 'content-type': 'text/event-stream' },
      body: [
        block('thinking', { delta: 'Дивлюся звіт користувача.' }),
        block('tool_call', { id: 't1', name: 'get_report', input: {} }),
        block('tool_result', { id: 't1', name: 'get_report', is_error: false, result: {} }),
        block('text', { delta: 'Позняки на 9,9 °C гарячіші.' }),
        block('validation', { ok: false, repairing: true, unsourced: [{ text: '9,9' }], caveats: [] }),
        block('text_reset', {}),
        block('text', { delta: '**Факти з даних**\n\nПоверхня забудови на 7,7 °C гарячіша за ліс. ' }),
        block('text', { delta: '[на мапі](uhd:place/kyiv-pozniaky)' }),
        block('done', { answer: '…', validation: { ok: true, unsourced: [] }, cost_usd: 0.07 }),
      ].join(''),
    });
  });
  await page.goto('/?lang=uk');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await chat.getByRole('textbox', { name: 'Ваше питання' }).fill('Наскільки Позняки гарячіші?');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  const answer = chat.getByTestId('chat-answer');
  await expect(answer).toContainText('Поверхня забудови на 7,7 °C гарячіша за ліс.');
  await expect(answer).not.toContainText('9,9');
  await expect(answer.locator('b').first()).toHaveText('Факти з даних');
  await expect(answer.getByText('перевіряє цифри звіту')).toBeVisible();
  await expect(answer.getByText('усі числа з даних')).toBeVisible();
  await expect(answer.getByText('Як міркував аналітик')).toBeVisible();
  await expect(answer.getByRole('button', { name: 'на мапі' })).toBeVisible();
  expect(sent).toHaveLength(1);
  expect(sent[0]!.team).toBeUndefined();
  expect((sent[0]!.body as { messages: unknown[] }).messages).toEqual([{ role: 'user', content: 'Наскільки Позняки гарячіші?' }]);
  expect((sent[0]!.body as { context: { lang?: string } }).context.lang).toBe('uk');
});

test('budget exhausted and stream errors are shown in Ukrainian; team mode sends the token', async ({ page }) => {
  let n = 0;
  const teams: (string | undefined)[] = [];
  await page.route('**/api/agent/chat', async (route) => {
    teams.push(route.request().headers()['x-uhd-team-token']);
    n += 1;
    if (n === 1) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'agent_budget_exhausted', message: 'daily budget' }) });
    } else {
      await route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' },
        body: block('text', { delta: 'чернетка' }) + block('error', { error: 'upstream_error', message: 'Claude API error 500' }) });
    }
  });
  await page.route('**/api/agent/tools', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ team: route.request().headers()['x-uhd-team-token'] === 'right-token', configured: true }),
  }));
  await page.goto('/?lang=uk');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  const input = chat.getByRole('textbox', { name: 'Ваше питання' });
  await input.fill('Привіт');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  await expect(chat.getByTestId('chat-error')).toHaveText(/Ліміт аналітика на сьогодні вичерпано/);
  await expect(page.getByTestId('agent-offline')).toHaveCount(0);

  // «Командний режим»: wrong key → message; right key → badge, header on the next request
  await chat.getByRole('button', { name: 'Командний режим' }).click();
  const key = chat.getByLabel('Ключ команди');
  await key.fill('wrong');
  await chat.getByRole('button', { name: 'Увімкнути' }).click();
  await expect(chat.getByText('Ключ не підійшов.')).toBeVisible();
  await key.fill('right-token');
  await chat.getByRole('button', { name: 'Увімкнути' }).click();
  await expect(chat.getByTestId('team-on')).toContainText('Командний режим увімкнено');

  await input.fill('Ще раз');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  await expect(chat.getByTestId('chat-error')).toHaveText(/Сервіс Claude зараз не відповідає/);
  await expect(chat).not.toContainText('Claude API error 500');
  await expect(chat).not.toContainText('чернетка');
  expect(teams).toEqual([undefined, 'right-token']);
  expect(await page.evaluate(() => document.documentElement.outerHTML.includes('right-token'))).toBe(false);
});

// Switch to English through the committed locale module (the same instance the app uses under Vite). Works before
// main.tsx reads ?lang= at boot (i18n 2b) and stays harmless after it.
async function toEnglish(page: Page) {
  // the module path is an argument, so tsc does not try to resolve a browser (Vite) URL
  await page.evaluate(async (path: string) => {
    const m = (await import(/* @vite-ignore */ path)) as { setLocale: (l: 'en' | 'uk') => void };
    m.setLocale('en');
  }, '/src/i18n/locale.ts');
}

test('English UI: chat texts, errors and context.lang follow the locale', async ({ page }) => {
  const bodies: { context: { lang?: string } }[] = [];
  await page.route('**/api/agent/chat', async (route) => {
    bodies.push(route.request().postDataJSON() as { context: { lang?: string } });
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'agent_budget_exhausted' }) });
  });
  await page.goto('/?lang=en');
  await ready(page);
  await toEnglish(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await expect(chat.getByRole('heading', { name: 'Analyst' })).toBeVisible();
  await expect(chat.getByRole('button', { name: 'Team mode' })).toBeVisible();
  await chat.getByRole('button', { name: 'Why is there no data for 2020?' }).click();
  await expect(chat.getByTestId('chat-error')).toHaveText(/limit for today is used up/);
  expect(bodies[0]!.context.lang).toBe('en');
  const panel = await chat.innerText();
  expect(panel).not.toMatch(/Аналітик|Надіслати|Командний|Ліміт/);
});

test('offline card in English when the analyst is not configured', async ({ page }) => {
  await page.route('**/api/agent/chat', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'agent_not_configured' }) }));
  await page.goto('/?lang=en');
  await ready(page);
  await toEnglish(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await chat.getByRole('textbox', { name: 'Your question' }).fill('Hello');
  await chat.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByTestId('agent-offline')).toContainText('The analyst is not connected yet');
  await expect(page.getByTestId('agent-offline')).toContainText('checks the weather on the image day (ERA5)');
});

test('a comparison table scrolls inside the panel, not the page (light and dark)', async ({ page }, info) => {
  const row = (n: string, a: string, b: string, c: string, d: string, e: string) => `| ${n} | ${a} | ${b} | ${c} | ${d} | ${e} |`;
  const table = [
    '**Факти з даних**', '',
    row('Район', 'Середній розрив, °C', 'Літо 2025, °C', 'Тренд, °C/10 р.', 'Значущість', 'NDVI, тренд/10 р.'),
    '|---|---:|---:|---:|---|---:|',
    row('Деснянський', '9,7', '8,28', '+0,21', 'незначущий', '+0,031'),
    row('Оболонський', '9,38', '9,12', '+0,35', 'незначущий', '+0,018'),
    row('Дарницький', '8,92', '8,2', '−0,05', 'незначущий', '+0,042'),
    '', 'Висновок: лідирують лівобережні райони; щорічні ряди — у [звіт](uhd:report/0123456789abcdef) кожного району.',
  ].join('\n');
  await page.route('**/api/agent/chat', (route) => route.fulfill({
    status: 200, headers: { 'content-type': 'text/event-stream' },
    body: block('text', { delta: table }) + block('done', { answer: table, validation: { ok: true, unsourced: [] }, cost_usd: 0.1 }),
  }));
  await page.goto('/?lang=uk');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await chat.getByRole('textbox', { name: 'Ваше питання' }).fill('Порівняй райони Києва таблицею');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  const wrap = chat.locator('.chat-table-wrap');
  await expect(wrap.locator('tbody tr')).toHaveCount(3);
  await expect(wrap.locator('td.num').first()).toHaveText('9,7');
  const m = await wrap.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, num: getComputedStyle(el.querySelector('table')!).fontVariantNumeric }));
  expect(m.sw).toBeGreaterThan(m.cw); // six columns do not fit the panel: the wrapper scrolls
  expect(m.num).toContain('tabular-nums');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await wrap.screenshot({ path: info.outputPath('table-light.png') });
  await page.emulateMedia({ colorScheme: 'dark' });
  await wrap.screenshot({ path: info.outputPath('table-dark.png') });
});

test('history survives a reload; «Нова розмова» clears it', async ({ page }) => {
  await page.route('**/api/agent/chat', (route) => route.fulfill({
    status: 200, headers: { 'content-type': 'text/event-stream' },
    body: block('text', { delta: 'Збережена відповідь.' }) + block('done', { answer: 'Збережена відповідь.', validation: { ok: true, unsourced: [] }, cost_usd: 0.01 }),
  }));
  await page.goto('/?lang=uk');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  await chat.getByRole('textbox', { name: 'Ваше питання' }).fill('Питання для пам’яті');
  await chat.getByRole('button', { name: 'Надіслати' }).click();
  await expect(chat.getByTestId('chat-answer')).toContainText('Збережена відповідь.');
  await page.reload();
  await ready(page);
  await page.getByTestId('ask').click();
  await expect(page.getByTestId('chat')).toContainText('Питання для пам’яті');
  await expect(page.getByTestId('chat').getByTestId('chat-answer')).toContainText('Збережена відповідь.');
  await page.getByTestId('chat').getByRole('button', { name: 'Нова розмова' }).click();
  await expect(page.getByTestId('chat')).not.toContainText('Питання для пам’яті');
  await page.reload();
  await ready(page);
  await page.getByTestId('ask').click();
  await expect(page.getByTestId('chat')).not.toContainText('Питання для пам’яті');
});

test('quote a selection and reply to a whole answer; the quote travels in the user message', async ({ page }) => {
  const sent: { messages: { role: string; content: string }[] }[] = [];
  await page.route('**/api/agent/chat', async (route) => {
    sent.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200, headers: { 'content-type': 'text/event-stream' },
      body: [
        block('text', { delta: 'Поверхня забудови на 7,7 °C гарячіша за ліс. Це літнє середнє.' }),
        block('done', { answer: '…', validation: { ok: true, unsourced: [] }, cost_usd: 0.01 }),
      ].join(''),
    });
  });
  await page.goto('/?lang=uk');
  await ready(page);
  await page.getByTestId('ask').click();
  const chat = page.getByTestId('chat');
  const input = chat.getByRole('textbox', { name: 'Ваше питання' });
  await input.fill('Наскільки гарячіше?');
  await input.press('Enter');
  const answer = chat.getByTestId('chat-answer');
  await expect(answer).toContainText('7,7 °C');
  // select a fragment of the answer → the floating «Цитувати» button
  await answer.locator('.chat-md p, .chat-md > div').first().evaluate((el) => {
    const node = el.firstChild!;
    const r = document.createRange();
    r.setStart(node, 0);
    r.setEnd(node, 'Поверхня забудови на 7,7 °C'.length);
    const s = window.getSelection()!;
    s.removeAllRanges();
    s.addRange(r);
  });
  await chat.getByTestId('chat-quote').click();
  await expect(input).toBeFocused();
  await expect(input).toHaveValue('> Поверхня забудови на 7,7 °C\n\n');
  // whole-answer reply (keyboard-reachable button); the quote is appended after what is typed
  await input.fill('');
  await answer.getByRole('button', { name: 'Відповісти на цю відповідь (цитує її)' }).focus();
  await page.keyboard.press('Enter');
  await expect(input).toBeFocused();
  await expect(input).toHaveValue(/^> Поверхня забудови на 7,7 °C гарячіша за ліс\. Це літнє середнє\.\n\n$/);
  await page.keyboard.type('А влітку 2024?');
  await page.keyboard.press('Enter');
  await expect(chat.getByTestId('msg-quote')).toHaveText('Поверхня забудови на 7,7 °C гарячіша за ліс. Це літнє середнє.');
  await expect(chat.locator('.msg.user .msg-rest').last()).toHaveText('А влітку 2024?');
  expect(sent).toHaveLength(2);
  expect(sent[1]!.messages.at(-1)!.content).toBe('> Поверхня забудови на 7,7 °C гарячіша за ліс. Це літнє середнє.\n\nА влітку 2024?');
});
