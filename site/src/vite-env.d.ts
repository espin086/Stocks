/// <reference types="vite/client" />
declare module "*.txt?raw" {
  const text: string;
  export default text;
}
