# Playwright 测试容器
FROM mcr.microsoft.com/playwright:v1.52.0-focal

WORKDIR /app

# 安装依赖
COPY package.json package-lock.json* ./
RUN npm ci

# 复制测试代码
COPY . .

# 安装浏览器（chromium-only 加速）
RUN npx playwright install chromium

CMD ["npx", "playwright", "test"]
