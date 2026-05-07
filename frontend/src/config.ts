const fallbackControllerUrl = 'http://localhost:5000'

const configuredControllerUrl = import.meta.env.VITE_CONTROLLER_URL?.trim()

export const controllerUrl = configuredControllerUrl || fallbackControllerUrl
