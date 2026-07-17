export default defineNitroPlugin((nitroApp) => {
  nitroApp.hooks.hook('request', (event) => {
    event.node.res.removeHeader('x-powered-by')
  })
})
