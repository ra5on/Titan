function escapeHtml(value: string) {
	return value
		.replaceAll('&', '&amp;')
		.replaceAll('<', '&lt;')
		.replaceAll('>', '&gt;')
		.replaceAll('"', '&quot;')
		.replaceAll("'", '&#39;')
}

export function appGatewayErrorPage({
	appName,
	appIcon,
	errorCode,
}: {
	appName: string
	appIcon: string
	errorCode?: string
}) {
	const name = escapeHtml(appName)
	const icon = escapeHtml(appIcon)
	const code = escapeHtml(errorCode || 'UPSTREAM_UNAVAILABLE')

	return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unable to connect to ${name}</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px;
      color: #171717;
      background: #fff;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      text-align: center;
    }
    main { max-width: 680px; }
    .icons {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 18px;
      margin-bottom: 34px;
    }
    .titan-logo { width: 100px; height: 100px; color: #232B3B; }
    .caret { width: 58px; height: 58px; color: #777; }
    .app-icon { width: 100px; height: 100px; border-radius: 20px; object-fit: cover; }
    h1 { margin: 0 0 12px; font-size: clamp(28px, 4vw, 40px); font-weight: 500; line-height: 1.2; }
    p { margin: 0; color: #6c757d; font-size: 16px; line-height: 1.5; }
    @media (prefers-color-scheme: dark) {
      body { color: #f5f5f5; background: #121212; }
      p { color: #aaa; }
      .caret { color: #999; }
      .titan-logo { color: #CBD7F0; }
    }
  </style>
</head>
<body>
  <main>
    <div class="icons" aria-hidden="true">
      <svg class="titan-logo" viewBox="0 0 96 96" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
        <path d="M7 14H65C54 19 45 27 39 38H7Z M83 14H89V38H72C64 38 60 43 60 51V79Q60 84 55 84H36V61C36 37 52 20 83 14Z"/>
      </svg>
      <svg class="caret" viewBox="0 0 32 32" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
        <path d="m18.629 15.997-7.083-7.081L13.462 7l8.997 8.997L13.457 25l-1.916-1.916z"/>
      </svg>
      <img class="app-icon" src="${icon}" alt="">
    </div>
    <h1>Oops, there was an error</h1>
    <p>There was an error connecting to ${name}. Error code: ${code}</p>
  </main>
</body>
</html>`
}
