import next from "eslint-config-next";
import security from "eslint-plugin-security";

export default [
  ...next(),
  security.configs.recommended,
  { ignores: [".next/**", "node_modules/**"] },
];
