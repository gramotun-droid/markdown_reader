import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {viteSingleFile} from 'vite-plugin-singlefile';

// Build the editor as a single self-contained index.html so it can be shipped
// inside the app and loaded from the local filesystem without asset-path fuss.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: '../app/assets/editor',
    emptyOutDir: true,
    chunkSizeWarningLimit: 8000,
  },
});
