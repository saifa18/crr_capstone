const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fs = require("fs");
const Lu = require("react-icons/lu");

const ICONS = {
  zap: "LuZap",
  users: "LuUsers",
  gitbranch: "LuGitBranch",
  gauge: "LuGauge",
  trending: "LuTrendingUp",
  target: "LuTarget",
  brain: "LuBrainCircuit",
  flask: "LuFlaskConical",
  presentation: "LuPresentation",
  map: "LuMap",
  database: "LuDatabase",
  code: "LuCode",
  shield: "LuShieldCheck",
  layers: "LuLayers",
  search: "LuSearch",
  checkcircle: "LuCircleCheckBig",
  arrowright: "LuArrowRight",
  lightbulb: "LuLightbulb",
};

async function run() {
  fs.mkdirSync("icons", { recursive: true });
  for (const [name, compName] of Object.entries(ICONS)) {
    const Comp = Lu[compName];
    const svg = ReactDOMServer.renderToStaticMarkup(
      React.createElement(Comp, { size: 256, color: "#3DDC97", strokeWidth: 1.6, xmlns: "http://www.w3.org/2000/svg" })
    );
    await sharp(Buffer.from(svg)).resize(256, 256).png().toFile(`icons/${name}.png`);

    const svgDark = ReactDOMServer.renderToStaticMarkup(
      React.createElement(Comp, { size: 256, color: "#0A0D13", strokeWidth: 1.6, xmlns: "http://www.w3.org/2000/svg" })
    );
    await sharp(Buffer.from(svgDark)).resize(256, 256).png().toFile(`icons/${name}_dark.png`);
  }
  console.log("icons rendered:", Object.keys(ICONS).length * 2);
}
run();
