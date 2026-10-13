"""Strict selector adapter. Website selectors must be verified for the user's UI.

No agent-supplied JavaScript, URLs, keyboard shortcuts or submit calls are executed.
"""
import asyncio
import re
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright


class BrowserError(RuntimeError):
    pass


class Browser:
    def __init__(self, root, profile):
        self.root, self.profile = Path(root).resolve(), profile
        self._page = self._context = self._playwright = None
        self.timeout = profile.get('timeout_ms', 10000)

    def _guard(self, url=None):
        parsed = urlparse(url or (self._page.url if self._page else ''))
        allowed = parsed.scheme == 'https' and parsed.hostname == 'jimeng.jianying.com'
        if self.profile.get('test_mode'):
            allowed |= parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
        if not allowed or parsed.username or parsed.password:
            raise BrowserError('浏览器不在允许的即梦官网页面')

    async def start(self, headless=False):
        if self._page and not self._page.is_closed():
            self._guard()
            return
        self._guard(self.profile['url'])
        self._playwright = await async_playwright().start()
        try:
            options = {'channel': self.profile['channel']} if self.profile.get('channel') else {}
            self._context = await self._playwright.chromium.launch_persistent_context(str(self.root/'browser-profile'), headless=headless, **options)
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            self._page.set_default_timeout(self.timeout)
            await self._page.goto(self.profile['url'], wait_until='domcontentloaded')
        except Exception as exc:
            await self.close()
            raise BrowserError('专用浏览器启动失败，请检查Chrome安装、浏览器配置及当前会话。不会接管日常浏览器。') from exc

    async def close(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = self._page = self._playwright = None

    async def inspect(self):
        """Read-only setup diagnostics, excluding input values, cookies and hidden DOM."""
        await self.start()
        self._guard()
        controls = await self._page.locator('button,[role="button"],[role="tab"],[role="combobox"],[data-testid],input[type="file"],[contenteditable="true"]').evaluate_all('''els => els.filter(e => e.getClientRects().length).slice(0,180).map(e => ({tag:e.tagName,role:e.getAttribute('role'),id:e.id,testid:e.getAttribute('data-testid'),label:e.getAttribute('aria-label'),text:(e.innerText||'').trim().slice(0,180)}))''')
        return {'title': await self._page.title(), 'url': self._page.url, 'controls': controls}

    async def one(self, selector, scope=None):
        if not selector:
            raise BrowserError('网页适配尚未配置；请按 docs/browser-adapter.md 核实 browser.local.json')
        loc = (scope or self._page).locator(selector)
        try:
            await loc.first.wait_for(state='attached', timeout=self.timeout)
            if await loc.count() != 1:
                raise BrowserError('网页元素不唯一，拒绝猜测操作目标')
            return loc
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserError('网页元素缺失：可能未登录、页面改版或配置不符') from exc

    async def value(self, locator):
        tag = await locator.evaluate('e => e.tagName.toLowerCase()')
        if tag == 'select':
            return (await locator.locator('option:checked').inner_text()).strip()
        if tag in ('input', 'textarea'):
            return (await locator.input_value()).strip()
        return (await locator.inner_text()).strip()

    def desired(self, task):
        return dict(task['generation'], duration_seconds=task['duration_seconds'], ratio=task['ratio'])

    def same(self, name, actual, value):
        if name in ('duration_seconds', 'count'):
            return actual in (str(value), f'{value}s', f'{value}秒', f'{value}条')
        return actual == str(value)

    async def controls(self, task, set_values=False):
        for name, value in self.desired(task).items():
            ctl = self.profile.get('controls', {}).get(name, {})
            loc = await self.one(ctl.get('read'))
            actual = await self.value(loc)
            if not self.same(name, actual, value) and set_values:
                if await loc.evaluate('e => e.tagName.toLowerCase()') == 'select':
                    labels = await loc.locator('option').all_text_contents()
                    match = [label for label in labels if self.same(name, label.strip(), value)]
                    if len(match) != 1:
                        raise BrowserError(f'找不到唯一的{name}目标选项')
                    await loc.select_option(label=match[0])
                else:
                    await (await self.one(ctl.get('trigger'))).click()
                    selector = ctl.get('option', '').replace('{value}', str(value))
                    await (await self.one(selector)).click()
                actual = await self.value(await self.one(ctl.get('read')))
            if not self.same(name, actual, value):
                raise BrowserError(f'{name} 实际值与任务不符，不会提交')

    async def refs(self, task):
        wanted = [m['name'] for m in task['materials']]
        count_loc = await self.one(self.profile.get('reference_count'))
        numbers = re.findall(r'\d+', await self.value(count_loc))
        if len(numbers) != 1 or int(numbers[0]) != len(wanted):
            raise BrowserError('素材面板数量与任务不符')
        selector = self.profile.get('reference_items')
        if not selector:
            raise BrowserError('缺少素材核对选择器')
        loc = self._page.locator(selector)
        if await loc.count() != len(wanted):
            raise BrowserError('素材元素数量与面板不符')
        for i, name in enumerate(wanted):
            item = loc.nth(i)
            await item.hover()
            observed = await item.get_attribute(self.profile.get('reference_name_attribute', 'title'))
            if not observed:
                observed = await self.value(await self.one(self.profile.get('reference_tooltip', '[role="tooltip"]')))
            if observed != name:
                raise BrowserError('素材文件名或顺序未能确认；不会点击缩略图重排')

    async def prepare(self, task):
        await self.start()
        self._guard()
        await self.controls(task, True)
        current = await self.value(await self.one(self.profile.get('reference_count')))
        numbers = re.findall(r'\d+', current)
        if len(numbers) != 1:
            raise BrowserError('无法确定现有素材数量')
        if int(numbers[0]) == 0:
            for index, material in enumerate(task['materials'], 1):
                await (await self.one(self.profile.get('upload'))).set_input_files(material['path'])
                for _ in range(20):
                    count = re.findall(r'\d+', await self.value(await self.one(self.profile['reference_count'])))
                    if count == [str(index)]:
                        break
                    await asyncio.sleep(.25)
                else:
                    raise BrowserError('上传后未确认素材数量增加')
        await self.refs(task)
        # fill() supports textarea and contenteditable and does not emit Enter key events.
        await (await self.one(self.profile.get('prompt'))).fill(task['design']['prompt'])

    async def number(self, key):
        text = await self.value(await self.one(self.profile.get(key)))
        numbers = re.findall(r'-?\d+(?:\.\d+)?', text.replace(',', ''))
        if len(numbers) != 1 or Decimal(numbers[0]) < 0:
            raise BrowserError('报价/余额存在多个数值或无效值，拒绝推测')
        return Decimal(numbers[0])

    async def cards(self):
        selector = self.profile.get('cards')
        attr = self.profile.get('card_id_attribute')
        if not selector or not attr:
            raise BrowserError('缺少任务卡识别配置')
        values = {}
        loc = self._page.locator(selector)
        for index in range(await loc.count()):
            card = loc.nth(index)
            key = await card.get_attribute(attr)
            if not key or key in values:
                raise BrowserError('任务卡缺少唯一ID，无法可靠恢复查询')
            values[key] = card
        return values

    async def quote(self, task):
        await self.start()
        self._guard()
        await self.controls(task)
        await self.refs(task)
        if await self.value(await self.one(self.profile.get('prompt'))) != task['design']['prompt'].strip():
            raise BrowserError('网页提示词与当前设计不一致')
        credits, balance = await self.number('credits'), await self.number('balance')
        evidence = f'evidence/quote-{uuid.uuid4().hex}.png'
        path = self.root/'tasks'/task['id']/evidence
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path))
        return dict(credits=float(credits), balance=float(balance), evidence=evidence, before_ids=list(await self.cards()))

    async def submit(self, task):
        self._guard()
        if not task.get('attempted') or not task.get('intent_id'):
            raise BrowserError('缺少已持久化的提交意图')
        await self.controls(task)
        await self.refs(task)
        if await self.number('credits') != Decimal(str(task['submission']['quote_credits'])):
            raise BrowserError('提交前报价再次变化，已停止')
        if await self.value(await self.one(self.profile.get('prompt'))) != task['design']['prompt'].strip():
            raise BrowserError('提交前提示词变化，已停止')
        if self.profile.get('collapse'):
            loc = self._page.locator(self.profile['collapse'])
            if await loc.count() == 1 and await loc.is_visible():
                await loc.click()
        prompt = await self.one(self.profile.get('prompt'))
        await prompt.focus()
        await prompt.press('Enter')

    async def reconcile(self, task):
        await self.start()
        self._guard()
        record = task['submission']
        candidates = []
        for key, card in (await self.cards()).items():
            if key in record['before_ids']:
                continue
            text = await self.value(await self.one(self.profile.get('card_prompt'), card))
            prompt = task['design']['prompt'].strip()
            if text == prompt or (len(prompt) >= 80 and prompt[:80] in text):
                candidates.append(key)
        balance = await self.number('balance')
        delta = Decimal(str(record['balance_before'])) - balance
        if len(candidates) != 1 or delta != Decimal(str(record['quote_credits'])):
            return dict(state='uncertain')
        path = self.root/'tasks'/task['id']/'evidence/submission.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path))
        return dict(state='confirmed', provider_task_id=candidates[0], balance_after=float(balance), credits_charged=float(delta), evidence='evidence/submission.png')

    async def card(self, task):
        await self.start()
        self._guard()
        card = (await self.cards()).get(task.get('provider_task_id'))
        if card is None:
            raise BrowserError('未找到已绑定的任务卡；请在专用浏览器进入对应记录后恢复')
        return card

    async def monitor(self, task):
        card = await self.card(task)
        status = await self.value(await self.one(self.profile.get('card_status'), card))
        if '失败' in status:
            return {'state': 'failed'}
        # Exact configured success labels; never treat “未完成” as completed.
        if status in self.profile.get('success_labels', ['完成', '生成成功']):
            return {'state': 'done'}
        return {'state': 'pending'}

    async def download(self, task):
        card = await self.card(task)
        button = await self.one(self.profile.get('download'), card)
        folder = self.root/'tasks'/task['id']/'downloads'
        folder.mkdir(parents=True, exist_ok=True)
        try:
            async with self._page.expect_download(timeout=60000) as info:
                await button.click()
            download = await info.value
            await download.save_as(folder/'original.mp4.part')
            if await download.failure():
                raise BrowserError('官网下载失败')
            (folder/'original.mp4.part').replace(folder/'original.mp4')
            return folder/'original.mp4'
        except Exception as exc:
            (folder/'original.mp4.part').unlink(missing_ok=True)
            raise BrowserError('下载失败，可恢复下载，不会重新生成') from exc
