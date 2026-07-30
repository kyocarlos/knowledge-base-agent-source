/**
 * Vue Router 設定
 */

import { createRouter, createWebHistory } from 'vue-router'
import SearchView from '../views/SearchView.vue'

const routes = [
  {
    path: '/',
    name: 'search',
    component: SearchView
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('../views/AdminView.vue')
  },
  {
    path: '/admin/chunks',
    name: 'chunk-viewer',
    component: () => import('../views/ChunkViewerView.vue')
  },
  {
    path: '/admin/report-reviews',
    name: 'report-reviews',
    component: () => import('../views/ReportReviewView.vue')
  },
  {
    path: '/upload',
    name: 'upload',
    component: () => import('../views/UploadView.vue')
  },
  {
    path: '/skills',
    name: 'skills',
    component: () => import('../views/SkillManagementView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
