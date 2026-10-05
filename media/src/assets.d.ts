// Font files imported by src/lib/fonts.ts: Remotion's bundler turns them into URLs.
declare module "*.ttf" {
  const url: string;
  export default url;
}
