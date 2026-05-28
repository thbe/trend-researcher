import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import vuetify from './plugins/vuetify'

import '@mdi/font/css/materialdesignicons.css'
import '@fontsource/roboto/400.css'
import '@fontsource/roboto/500.css'
import '@fontsource/roboto/700.css'

const app = createApp(App)
// Pinia must be installed before router + vuetify so that store hooks called
// from router guards and component setup() resolve against an active pinia.
app.use(createPinia())
app.use(router)
app.use(vuetify)
app.mount('#app')
