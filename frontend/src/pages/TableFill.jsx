import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Upload,
  Play,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  ArrowRight,
  Layers,
} from 'lucide-react'
import { PageShell, LiveStatus } from '@/components/page/PageShell'
import { InfoPanelCard } from '@/components/page/SectionLabel'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Textarea, Label } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { FileDropzone } from '@/components/ui/FileDropzone'
import { useToast } from '@/components/ui/Toast'
import { ingestMaterials, listMaterials, processTemplate } from '@/lib/api'
import { downloadBlob } from '@/lib/utils'
import { MaterialsSummaryCard } from '@/components/workspace/MaterialsSummaryCard'
import { PipelineMiniViz } from '@/components/workspace/PipelineMiniViz'
import { RecentRunsCard } from '@/components/workspace/RecentRunsCard'

const CHANNEL_LABEL = { excel: 'Excel', md_txt: 'MD/TXT', word: 'Word' }

export function TableFill() {
  // Step 1: ingest
  const [excelFiles, setExcelFiles] = useState([])
  const [mdTxtFiles, setMdTxtFiles] = useState([])
  const [wordFiles, setWordFiles] = useState([])
  const [ingesting, setIngesting] = useState(false)
  const [materials, setMaterials] = useState(null)

  // Step 2: process
  const [templateFile, setTemplateFile] = useState([])
  const [requirement, setRequirement] = useState('')
  const [processing, setProcessing] = useState(false)

  const location = useLocation()
  const toast = useToast()

  useEffect(() => {
    if (location.state?.requirement) setRequirement(location.state.requirement)
  }, [location.state])

  const refreshMaterials = async () => {
    try {
      setMaterials(await listMaterials())
    } catch (e) {
      /* silent */
    }
  }
  useEffect(() => {
    refreshMaterials()
  }, [])

  const handleIngest = async () => {
    const total = excelFiles.length + mdTxtFiles.length + wordFiles.length
    if (total === 0) return toast.error('请至少上传一份素材')
    setIngesting(true)
    try {
      const res = await ingestMaterials({
        excel: excelFiles,
        mdTxt: mdTxtFiles,
        word: wordFiles,
      })
      toast.success(`素材入库完成 · 成功 ${res.succeeded} / ${res.count}`)
      setExcelFiles([])
      setMdTxtFiles([])
      setWordFiles([])
      await refreshMaterials()
    } catch (e) {
      toast.error(`入库失败: ${e.message}`)
    } finally {
      setIngesting(false)
    }
  }

  const handleProcess = async () => {
    if (!templateFile.length) return toast.error('请上传模板文件')
    if (!materials || materials.count === 0)
      return toast.error('素材库为空，请先上传素材')
    setProcessing(true)
    try {
      const blob = await processTemplate(templateFile[0], requirement)
      const baseName = templateFile[0].name.replace(/\.(docx|xlsx)$/i, '')
      const ext = templateFile[0].name.toLowerCase().endsWith('.xlsx')
        ? 'xlsx'
        : 'docx'
      downloadBlob(blob, `${baseName}_filled.${ext}`)
      toast.success('表格填写完成，文件已开始下载')
    } catch (e) {
      toast.error(`填表失败: ${e.message}`)
    } finally {
      setProcessing(false)
    }
  }

  // 推导右栏 pipeline 当前所处阶段
  const pipelineStage = processing
    ? 'retrieve'
    : ingesting
      ? 'ingest'
      : materials?.count > 0
        ? 'build'
        : null

  const totalUpload = excelFiles.length + mdTxtFiles.length + wordFiles.length

  return (
    <PageShell
      breadcrumb={['工作台', '表格智能填写']}
      status={<LiveStatus meta="qwen-plus · 128k" />}
    >
      {/* Compact header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 mb-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-ink-900 tracking-tight">表格智能填写</h1>
            <Badge variant="primary" className="gap-1">
              <Layers className="w-3 h-3" />
              模块 ③
            </Badge>
            <Badge variant="default">素材 → 模板 → 填表</Badge>
            <span className="hidden sm:inline text-[11px] text-ink-400 font-mono">avg 65 s</span>
          </div>
          <p className="text-xs text-ink-500">素材按通道分类入库后可被多次复用。模板可以是 .docx 或 .xlsx 格式,自动识别占位并按业务语义对齐。</p>
        </div>
      </div>

      <div className="flex gap-8">
        {/* 主内容 */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Step 1 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2.5">
                <StepMark active={pipelineStage === null || pipelineStage === 'ingest'}>
                  1
                </StepMark>
                上传参考素材
              </CardTitle>
              <CardDescription>
                按类型分类上传。素材入库后可被多次填表复用。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <ChannelDropzone
                  label="Excel 数据表"
                  accept=".xlsx,.xls,.xlsm"
                  files={excelFiles}
                  onChange={setExcelFiles}
                />
                <ChannelDropzone
                  label="MD / TXT 文档"
                  accept=".md,.markdown,.txt"
                  files={mdTxtFiles}
                  onChange={setMdTxtFiles}
                />
                <ChannelDropzone
                  label="Word 文档"
                  accept=".docx"
                  files={wordFiles}
                  onChange={setWordFiles}
                />
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleIngest} loading={ingesting}>
                  <Upload className="w-4 h-4" />
                  入库素材
                </Button>
                <span className="text-xs text-ink-500">
                  已选:{' '}
                  <span className="font-mono text-ink-700">{totalUpload}</span>{' '}
                  份
                  {ingesting && ' · 可能需要几分钟 (OCR + 树构建)'}
                </span>
              </div>

              {/* Current library inline */}
              {materials && materials.count > 0 && (
                <div className="mt-5 pt-4 border-t border-ink-100">
                  <div className="text-[11px] font-semibold text-ink-500 uppercase tracking-wider mb-2">
                    当前素材库 · {materials.count} 份 ·{' '}
                    <span className="text-emerald-700">
                      成功 {materials.succeeded}
                    </span>
                  </div>
                  <ul className="space-y-1.5 max-h-40 overflow-y-auto scroll-thin">
                    {materials.docs.map((d, i) => (
                      <li
                        key={i}
                        className="flex items-center gap-2 text-xs text-ink-600"
                      >
                        {d.status === 'ok' ? (
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                        ) : (
                          <AlertCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                        )}
                        <Badge variant="default" className="shrink-0">
                          {CHANNEL_LABEL[d.channel]}
                        </Badge>
                        <span className="truncate">{d.original_name}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Step 2 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2.5">
                <StepMark
                  active={pipelineStage === 'retrieve' || pipelineStage === 'build'}
                >
                  2
                </StepMark>
                上传空白模板并填写
              </CardTitle>
              <CardDescription>模板可以是 .docx (含表格) 或 .xlsx</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>模板文件</Label>
                <FileDropzone
                  accept=".docx,.xlsx"
                  files={templateFile}
                  onFilesChange={setTemplateFile}
                />
              </div>

              <div>
                <Label>填表要求 · 自然语言,可选</Label>
                <Textarea
                  placeholder="例如:只填写 2024 年的德州市数据"
                  value={requirement}
                  onChange={(e) => setRequirement(e.target.value)}
                  rows={3}
                />
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-ink-100">
                <span className="text-xs text-ink-500">
                  {processing
                    ? '复杂表格可能需要 1–3 分钟,请耐心等待'
                    : '填表成功后文件会自动开始下载'}
                </span>
                <Button
                  onClick={handleProcess}
                  loading={processing}
                  size="lg"
                >
                  <Play className="w-4 h-4" />
                  {processing ? '处理中…' : '开始填表'}
                  {!processing && <ArrowRight className="w-3.5 h-3.5" />}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 右侧信息栏 */}
        <div className="hidden lg:flex flex-col gap-4 w-72 shrink-0">
          <PipelineMiniViz currentStage={pipelineStage} />
          <MaterialsSummaryCard materials={materials} />
          <TipsCard />
        </div>
      </div>
    </PageShell>
  )
}

/** 小型步骤标记,在 ingest/fill 时 primary,其它时 ink */
function StepMark({ children, active }) {
  return (
    <span
      className={
        active
          ? 'w-6 h-6 rounded-md border border-primary-200 bg-primary-50 text-xs font-mono text-primary-600 flex items-center justify-center'
          : 'w-6 h-6 rounded-md border border-ink-200 bg-ink-50 text-xs font-mono text-ink-600 flex items-center justify-center'
      }
    >
      {children}
    </span>
  )
}

function ChannelDropzone({ label, accept, files, onChange }) {
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <FileDropzone
        accept={accept}
        multiple
        files={files}
        onFilesChange={onChange}
      />
    </div>
  )
}

/** 右栏底部小贴士 */
function TipsCard() {
  return (
    <InfoPanelCard label="Tips">
      <ul className="space-y-2 text-xs text-ink-600">
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>按通道分类上传可提高匹配精度</span>
        </li>
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>填表要求越具体,结果越稳</span>
        </li>
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>同一批素材可填多个模板,无需重复上传</span>
        </li>
      </ul>
    </InfoPanelCard>
  )
}
