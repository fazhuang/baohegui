import { Page, request, expect } from '@playwright/test';

/**
 * 测试常量
 */
export const TEST_USER = {
  username: 'playwright-test-user',
  password: 'test123456',
  company: 'Playwright 测试公司',
  email: 'playwright@test.com',
};

export const API_BASE = 'http://backend:8000';
export const FRONTEND_BASE = 'http://frontend:80';

/**
 * 通过 API 注册并登录，返回 access_token
 */
export async function apiRegisterAndLogin(): Promise<string> {
  const ctx = await request.newContext({ baseURL: API_BASE });

  // 先尝试登录
  const loginRes = await ctx.post('/api/auth/login', {
    data: { username: TEST_USER.username, password: TEST_USER.password },
  });
  if (loginRes.ok()) {
    const data = await loginRes.json();
    return data.access_token;
  }

  // 未注册则注册
  const regRes = await ctx.post('/api/auth/register', {
    data: TEST_USER,
  });
  if (!regRes.ok()) {
    throw new Error(`注册失败: ${regRes.status()} ${await regRes.text()}`);
  }
  const data = await regRes.json();
  return data.access_token;
}

/**
 * 通过 API 设置前端认证（localStorage），然后导航到目标页面
 */
export async function loginViaApi(page: Page, targetPath = '/') {
  const token = await apiRegisterAndLogin();

  await page.goto(FRONTEND_BASE + '/login');
  await page.evaluate(
    ({ t, role, username }) => {
      localStorage.setItem('token', t);
      localStorage.setItem('role', role);
      localStorage.setItem('username', username);
    },
    { t: token, role: 'user', username: TEST_USER.username },
  );

  await page.goto(FRONTEND_BASE + targetPath);
  await page.waitForLoadState('networkidle');
}

/**
 * 通过开发模式的"一键登录"按钮快速进入（admin 权限）
 */
export async function devQuickLogin(page: Page) {
  await page.goto(FRONTEND_BASE + '/login');
  await page.waitForLoadState('networkidle');

  // 点击"开发模式 · 一键登录"按钮
  await page.getByRole('button', { name: /一键登录|开发模式/ }).click();
  await page.waitForURL('**/');
  await page.waitForLoadState('networkidle');
}

/**
 * 生成一个测试用的 docx 文件（最小合法 Word 文档）
 * 返回文件路径，可用于 input[type=file] 上传
 */
export function createTestDocx(page: Page): Promise<string> {
  return page.evaluate(async () => {
    // 使用纯 JS 生成最小 docx（ZIP 格式）
    // DOCX 本质是一个 ZIP 包，包含 [Content_Types].xml 等文件
    const encoder = new TextEncoder();

    // 构建 ZIP 条目
    const files: { name: string; data: Uint8Array }[] = [];

    // [Content_Types].xml
    files.push({
      name: '[Content_Types].xml',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
          '</Types>',
      ),
    });

    // _rels/.rels
    files.push({
      name: '_rels/.rels',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
          '</Relationships>',
      ),
    });

    // word/document.xml
    const docContent = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>第一章 招标公告</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>本采购项目采用公开招标方式，欢迎合格供应商投标。预算金额500万元。</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>第二章 投标人资格要求</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>1. 投标人应具有独立承担民事责任的能力。</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>2. 投标人必须为本市注册企业，注册资本不低于1000万元。</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>第三章 评审办法</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>本项目采用综合评分法。技术方案40分，价格30分，业绩30分。</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>第四章 投标须知</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>投标截止时间：2026年7月1日9:00。投标有效期90天。</w:t></w:r>
    </w:p>
  </w:body>
</w:document>`;

    files.push({
      name: 'word/document.xml',
      data: encoder.encode(docContent),
    });

    // word/_rels/document.xml.rels
    files.push({
      name: 'word/_rels/document.xml.rels',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
          '</Relationships>',
      ),
    });

    // word/styles.xml
    files.push({
      name: 'word/styles.xml',
      data: encoder.encode(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
          '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr></w:style>' +
          '</w:styles>',
      ),
    });

    // 使用 JSZip 构建 ZIP
    // 由于页面不一定有 JSZip，我们用 Blob + 手动构建简单 ZIP
    // 最小 ZIP 结构：仅存储（不压缩）
    function makeZip(entries: { name: string; data: Uint8Array }[]): Blob {
      const localHeaders: Uint8Array[] = [];
      const centralHeaders: Uint8Array[] = [];
      let offset = 0;

      for (const entry of entries) {
        const nameBytes = encoder.encode(entry.name);
        const crc = crc32(entry.data);

        // Local file header
        const lh = new Uint8Array(30 + nameBytes.length);
        const lv = new DataView(lh.buffer);
        lv.setUint32(0, 0x04034b50, true); // signature
        lv.setUint16(4, 20, true); // version needed
        lv.setUint16(6, 0, true); // flags
        lv.setUint16(8, 0, true); // compression: store
        lv.setUint16(10, 0, true); // mod time
        lv.setUint16(12, 0, true); // mod date
        lv.setUint32(14, crc, true); // crc32
        lv.setUint32(18, entry.data.length, true); // compressed size
        lv.setUint32(22, entry.data.length, true); // uncompressed size
        lv.setUint16(26, nameBytes.length, true); // filename length
        lh.set(nameBytes, 30);

        localHeaders.push(lh);
        localHeaders.push(entry.data);

        // Central directory header
        const ch = new Uint8Array(46 + nameBytes.length);
        const cv = new DataView(ch.buffer);
        cv.setUint32(0, 0x02014b50, true); // signature
        cv.setUint16(4, 20, true); // version made by
        cv.setUint16(6, 20, true); // version needed
        cv.setUint16(8, 0, true); // flags
        cv.setUint16(10, 0, true); // compression
        cv.setUint16(12, 0, true); // mod time
        cv.setUint16(14, 0, true); // mod date
        cv.setUint32(16, crc, true); // crc32
        cv.setUint32(20, entry.data.length, true); // compressed
        cv.setUint32(24, entry.data.length, true); // uncompressed
        cv.setUint16(28, nameBytes.length, true); // filename length
        cv.setUint16(30, 0, true); // extra field length
        cv.setUint16(32, 0, true); // file comment length
        cv.setUint16(34, 0, true); // disk number
        cv.setUint16(36, 0, true); // internal attrs
        cv.setUint32(38, 0, true); // external attrs
        cv.setUint32(42, offset, true); // local header offset
        ch.set(nameBytes, 46);

        centralHeaders.push(ch);

        offset += lh.length + entry.data.length;
      }

      // End of central directory
      const centralSize = centralHeaders.reduce((s, h) => s + h.length, 0);
      const centralOffset = localHeaders.reduce((s, h) => s + h.length, 0);
      const eocd = new Uint8Array(22);
      const ev = new DataView(eocd.buffer);
      ev.setUint32(0, 0x06054b50, true);
      ev.setUint16(4, 0, true); // disk
      ev.setUint16(6, 0, true); // disk of central
      ev.setUint16(8, entries.length, true); // entries on disk
      ev.setUint16(10, entries.length, true); // total entries
      ev.setUint32(12, centralSize, true);
      ev.setUint32(16, centralOffset, true);
      ev.setUint16(20, 0, true); // comment length

      const allParts = [...localHeaders, ...centralHeaders, eocd];
      return new Blob(allParts, { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
    }

    // CRC32 实现
    function crc32(data: Uint8Array): number {
      let crc = 0xffffffff;
      for (let i = 0; i < data.length; i++) {
        crc ^= data[i];
        for (let j = 0; j < 8; j++) {
          crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
        }
      }
      return (crc ^ 0xffffffff) >>> 0;
    }

    const blob = makeZip(files);
    const url = URL.createObjectURL(blob);

    // 为了能通过 input[type=file] 上传，我们需要创建一个 File 对象
    // 但由于 File 构造函数需要文件路径，我们用 DataTransfer
    const file = new File([blob], 'test_bidding_doc.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    });

    // 保存到全局以便测试使用
    (window as any).__testDocxFile = file;
    return url;
  });
}

/**
 * 使用 Ant Design Upload 组件上传文件（拖拽上传模式）
 */
export async function uploadFileViaUI(page: Page, file: { name: string; mimeType: string; buffer: Buffer }) {
  // 找到拖拽上传区域中的 input[type=file]
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles([file]);
  await page.waitForTimeout(2000); // 等待上传完成
}

/**
 * 等待 Ant Design Spin/loading 消失
 */
export async function waitForAntdLoading(page: Page, timeout = 15000) {
  // Ant Design 加载中通常带有 ant-spin 类
  const spin = page.locator('.ant-spin-spinning');
  if (await spin.isVisible({ timeout: 3000 }).catch(() => false)) {
    await spin.waitFor({ state: 'hidden', timeout });
  }
}

/**
 * 检查页面是否包含指定文本（忽略大小写）
 */
export async function expectText(page: Page, text: string | RegExp) {
  await expect(page.getByText(text).first()).toBeVisible({ timeout: 5000 });
}

/**
 * 通过 API 上传文件并返回 file_id
 */
export async function apiUploadTestFile(token: string): Promise<number> {
  const ctx = await request.newContext({ baseURL: API_BASE });

  // 用 Python 在服务端生成测试文档（利用容器内已有 python3）
  // 这里通过 API 上传我们预先准备的测试文件
  const resp = await ctx.post('/api/upload/', {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    multipart: {
      file: {
        name: 'test_bidding_doc.docx',
        mimeType:
          'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        buffer: Buffer.from('dummy'), // 会被替换
      },
    },
  });

  if (!resp.ok()) {
    throw new Error(`上传失败: ${resp.status()} ${await resp.text()}`);
  }
  const data = await resp.json();
  return data.db_id;
}
