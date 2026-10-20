/** Portrait only. The game's original bottom subtitle remains the sole caption. */
export function anniePage() {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>安妮 · 桌面小导演</title>
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;color:#fff}canvas{display:block;width:100%;height:100%;visibility:hidden}body[data-speaking="true"] canvas{visibility:visible}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
</style>
<script type="importmap">{"imports":{"three":"/vendor/annie-lib/three/build/three.module.js","three/addons/":"/vendor/annie-lib/three/examples/jsm/","@pixiv/three-vrm":"/vendor/annie-lib/vrm/three-vrm.module.min.js"}}</script></head>
<body data-speaking="false"><canvas id="avatar" aria-label="字幕左侧的小导演兼解说 Annie"></canvas><p id="status" class="sr-only" role="status">等待小导演讲述</p><script type="module" src="/vendor/open-annie/presenter.js"></script></body></html>`;
}
