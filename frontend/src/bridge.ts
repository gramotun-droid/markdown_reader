// Typed wrapper around the QWebChannel object exposed by the Python side.

export type Theme = 'light' | 'dark';

type Signal<Args extends unknown[]> = {
  connect: (cb: (...args: Args) => void) => void;
  disconnect?: (cb: (...args: Args) => void) => void;
};

export type EditorBridge = {
  // Python -> JS
  contentSet: Signal<[string, string]>; // (markup, theme)
  themeChanged: Signal<[string]>;
  // JS -> Python (slots)
  ready: () => void;
  onContentChanged: (markup: string) => void;
  onSave: (markup: string) => void;
  onCancel: () => void;
};

declare global {
  interface Window {
    qt?: {webChannelTransport: unknown};
    QWebChannel?: new (transport: unknown, cb: (channel: {objects: {bridge: EditorBridge}}) => void) => void;
  }
}

export function connectBridge(onConnect: (bridge: EditorBridge) => void): void {
  const {qt, QWebChannel} = window;
  if (qt?.webChannelTransport && QWebChannel) {
    new QWebChannel(qt.webChannelTransport, (channel) => onConnect(channel.objects.bridge));
  }
  // No transport => running outside the app (dev). Caller handles the null case.
}
