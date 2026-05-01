import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import { createApp } from "vue";
import VxeUITable from "vxe-table";
import "vxe-table/lib/style.css";
import App from "./App.vue";
import "./styles.css";

createApp(App).use(ElementPlus, { locale: zhCn }).use(VxeUITable).mount("#app");
