// バックエンドAPIの接続先。
//
// 同一オリジン配信（FastAPIがフロントも配る場合）は空文字のままでOK。
// VercelなどにPWAだけ置き、バックエンドを別ホスト（Fly.io等）に置く場合は、
// ここにバックエンドの公開URLを設定する。例:
//
//   window.__API_BASE__ = "https://geiyo-bus.fly.dev";
//
// ※ デプロイ前にこの1行を書き換えてください。
//   （未設定でも、ブラウザのコンソールで localStorage.setItem("apiBase", "https://...") でも上書き可）
window.__API_BASE__ = "";
