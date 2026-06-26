import React, {useEffect, useMemo, useState} from 'react';
import {ThemeProvider, Toaster, ToasterComponent, ToasterProvider} from '@gravity-ui/uikit';
import {MarkdownEditorView, useMarkdownEditor} from '@gravity-ui/markdown-editor';

import '@gravity-ui/uikit/styles/fonts.css';
import '@gravity-ui/uikit/styles/styles.css';

import {connectBridge, type EditorBridge, type Theme} from './bridge';

function normalizeTheme(value: string): Theme {
  return value === 'dark' ? 'dark' : 'light';
}

function Editor({markup, bridge}: {markup: string; bridge: EditorBridge | null}) {
  // Recreate the editor when a different document is loaded.
  const editor = useMarkdownEditor(
    {
      md: {html: false, linkify: true, breaks: true},
      initial: {markup, mode: 'wysiwyg'},
    },
    [markup],
  );

  useEffect(() => {
    if (!bridge) return;
    let timer: number | undefined;
    const onChange = () => {
      window.clearTimeout(timer);
      // Debounce: this only feeds the "modified?" check; saving sends the exact
      // current value separately.
      timer = window.setTimeout(() => bridge.onContentChanged(editor.getValue()), 300);
    };
    editor.on('change', onChange);
    return () => {
      window.clearTimeout(timer);
      editor.off('change', onChange);
    };
  }, [editor, bridge]);

  // Test/debug hook: lets the host read the current markup synchronously.
  useEffect(() => {
    (window as unknown as {__mdeGetValue?: () => string}).__mdeGetValue = () => editor.getValue();
  }, [editor]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const meta = event.ctrlKey || event.metaKey;
      if (meta && event.key.toLowerCase() === 's') {
        event.preventDefault();
        bridge?.onSave(editor.getValue());
      } else if (event.key === 'Escape') {
        bridge?.onCancel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editor, bridge]);

  return (
    <div className="mde-wrap">
      <MarkdownEditorView editor={editor} stickyToolbar autofocus />
    </div>
  );
}

export function App() {
  const [bridge, setBridge] = useState<EditorBridge | null>(null);
  const [theme, setTheme] = useState<Theme>('light');
  const [markup, setMarkup] = useState<string | null>(null);

  useEffect(() => {
    let connected = false;
    connectBridge((b) => {
      connected = true;
      b.contentSet.connect((nextMarkup: string, nextTheme: string) => {
        setTheme(normalizeTheme(nextTheme));
        setMarkup(nextMarkup);
      });
      b.themeChanged.connect((nextTheme: string) => setTheme(normalizeTheme(nextTheme)));
      setBridge(b);
      b.ready();
    });
    // Running outside the app (browser dev): show a placeholder document.
    if (!connected && !window.qt) {
      setMarkup('# MD Reader\n\nРедактор запущен вне приложения.\n');
    }
  }, []);

  const toaster = useMemo(() => new Toaster(), []);

  return (
    <ToasterProvider toaster={toaster}>
      <ThemeProvider theme={theme}>
        {markup === null ? (
          <div className="mde-loading">Загрузка редактора…</div>
        ) : (
          <Editor markup={markup} bridge={bridge} />
        )}
        <ToasterComponent />
      </ThemeProvider>
    </ToasterProvider>
  );
}
